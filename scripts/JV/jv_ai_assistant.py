# jv_ai_assistant.py - AI-Powered J-V Analysis Assistant (Gemini API)
"""
AI features:
1. Anomaly Detection - detect J-V curve anomalies
3. Equivalent Circuit Parameter Extraction - extract physical parameters
4. Optimal Sample Recommendation - recommend optimal conditions
5. Natural Language Report Generation - auto report generation

Features:
- store/load historical data (SQLite)
- prevent duplicate data (hash-based)
- chat feature
"""

import os
import json
import sqlite3
import hashlib
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any, Tuple
import threading

import pandas as pd
import numpy as np

# Gemini API
try:
    import warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=FutureWarning)
        import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    genai = None
    print("Warning: google-generativeai not installed. Run: pip install google-generativeai")
except Exception as e:
    GEMINI_AVAILABLE = False
    genai = None
    print(f"Warning: Could not load google-generativeai: {e}")


# =========================
# Configuration
# =========================
@dataclass
class AIConfig:
    api_key: str = ""
    model_name: str = "gemini-2.0-flash"  # Updated to latest model
    db_path: str = "jv_ai_history.db"
    max_history_per_sample: int = 5  # max stored history per sample


# =========================
# Database Manager (store/manage historical data)
# =========================
class JVDataManager:
    """SQLite-based J-V data management - dedup and history"""

    def __init__(self, db_path: str = "jv_ai_history.db"):
        self.db_path = db_path
        self._init_database()

    def _init_database(self):
        """Initialize database tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # samples table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_hash TEXT UNIQUE,
                    filename TEXT,
                    voc REAL,
                    jsc REAL,
                    ff REAL,
                    pce REAL,
                    raw_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # AI analysis results table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS analysis_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sample_hash TEXT,
                    analysis_type TEXT,
                    result TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (sample_hash) REFERENCES samples(data_hash)
                )
            """)

            # conversation history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    role TEXT,
                    message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # recommendation history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    context_hash TEXT,
                    recommendation TEXT,
                    feedback TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()

    @staticmethod
    def _safe_round(v, ndigits):
        """Non-numeric summary fields ("non") must not crash hashing/storage."""
        try:
            return round(float(v), ndigits)
        except (TypeError, ValueError):
            return None

    def _compute_hash(self, data: Dict) -> str:
        """Compute data hash (for dedup)"""
        # hash only key values (filename + main parameters)
        key_data = {
            'filename': data.get('filename', ''),
            'voc': self._safe_round(data.get('voc', 0), 3),
            'jsc': self._safe_round(data.get('jsc', 0), 2),
            'ff': self._safe_round(data.get('ff', 0), 2),
            'pce': self._safe_round(data.get('pce', 0), 2)
        }
        hash_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(hash_str.encode()).hexdigest()

    def save_sample(self, sample_data: Dict, raw_jv_data: pd.DataFrame = None) -> Tuple[bool, str]:
        """
        Store sample data (skip if duplicate)
        Returns: (is_new, data_hash)
        """
        data_hash = self._compute_hash(sample_data)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # duplicate check
            cursor.execute("SELECT id FROM samples WHERE data_hash = ?", (data_hash,))
            if cursor.fetchone():
                return False, data_hash  # already exists

            # store new data
            raw_data_json = raw_jv_data.to_json() if raw_jv_data is not None else None

            def _safe_float(v):
                # summary fields can legitimately be non-numeric ("non") when
                # the instrument summary block was missing or unparseable;
                # float("non") crashed the whole AI report generation
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            cursor.execute("""
                INSERT INTO samples (data_hash, filename, voc, jsc, ff, pce, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                data_hash,
                sample_data.get('filename', ''),
                _safe_float(sample_data.get('voc', 0)),
                _safe_float(sample_data.get('jsc', 0)),
                _safe_float(sample_data.get('ff', 0)),
                _safe_float(sample_data.get('pce', 0)),
                raw_data_json
            ))
            conn.commit()

        return True, data_hash

    def save_batch_samples(self, samples_df: pd.DataFrame) -> Dict[str, Any]:
        """Batch-store samples - excluding duplicates"""
        new_count = 0
        duplicate_count = 0

        for _, row in samples_df.iterrows():
            sample_data = {
                'filename': row.get('Filename', ''),
                'voc': row.get('Voc V', 0),
                'jsc': row.get('Jsc mA/cm2', 0),
                'ff': row.get('Fill Factor', 0),
                'pce': row.get('PCE (%)', 0)
            }
            is_new, _ = self.save_sample(sample_data)
            if is_new:
                new_count += 1
            else:
                duplicate_count += 1

        return {
            'new': new_count,
            'duplicates': duplicate_count,
            'total': new_count + duplicate_count
        }

    def get_all_samples(self) -> pd.DataFrame:
        """Query all stored samples"""
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query("""
                SELECT filename, voc, jsc, ff, pce, created_at
                FROM samples
                ORDER BY created_at DESC
            """, conn)
        return df

    def get_sample_statistics(self) -> Dict[str, Any]:
        """Stored-sample statistics"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM samples")
            total = cursor.fetchone()[0]

            cursor.execute("""
                SELECT AVG(voc), AVG(jsc), AVG(ff), AVG(pce),
                       MAX(pce), MIN(pce)
                FROM samples
            """)
            stats = cursor.fetchone()

        return {
            'total_samples': total,
            'avg_voc': stats[0],
            'avg_jsc': stats[1],
            'avg_ff': stats[2],
            'avg_pce': stats[3],
            'max_pce': stats[4],
            'min_pce': stats[5]
        }

    def save_analysis_result(self, sample_hash: str, analysis_type: str, result: str):
        """Store analysis result"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO analysis_results (sample_hash, analysis_type, result)
                VALUES (?, ?, ?)
            """, (sample_hash, analysis_type, result))
            conn.commit()

    def get_analysis_history(self, analysis_type: str = None, limit: int = 10) -> List[Dict]:
        """Query analysis history"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            if analysis_type:
                cursor.execute("""
                    SELECT ar.analysis_type, ar.result, ar.created_at, s.filename
                    FROM analysis_results ar
                    LEFT JOIN samples s ON ar.sample_hash = s.data_hash
                    WHERE ar.analysis_type = ?
                    ORDER BY ar.created_at DESC
                    LIMIT ?
                """, (analysis_type, limit))
            else:
                cursor.execute("""
                    SELECT ar.analysis_type, ar.result, ar.created_at, s.filename
                    FROM analysis_results ar
                    LEFT JOIN samples s ON ar.sample_hash = s.data_hash
                    ORDER BY ar.created_at DESC
                    LIMIT ?
                """, (limit,))

            results = []
            for row in cursor.fetchall():
                results.append({
                    'type': row[0],
                    'result': row[1],
                    'created_at': row[2],
                    'filename': row[3]
                })

        return results

    def save_chat_message(self, session_id: str, role: str, message: str):
        """Store conversation message"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO chat_history (session_id, role, message)
                VALUES (?, ?, ?)
            """, (session_id, role, message))
            conn.commit()

    def get_chat_history(self, session_id: str, limit: int = 20) -> List[Dict]:
        """Query conversation history"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT role, message, created_at
                FROM chat_history
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (session_id, limit))

            results = []
            for row in cursor.fetchall():
                results.append({
                    'role': row[0],
                    'message': row[1],
                    'created_at': row[2]
                })

        return list(reversed(results))  # chronological order

    def cleanup_old_data(self, days: int = 30):
        """Clean up old data"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # delete old analysis results
            cursor.execute("""
                DELETE FROM analysis_results
                WHERE created_at < datetime('now', ?)
            """, (f'-{days} days',))

            # delete old chat history
            cursor.execute("""
                DELETE FROM chat_history
                WHERE created_at < datetime('now', ?)
            """, (f'-{days} days',))

            conn.commit()


# =========================
# Gemini AI Assistant
# =========================
class JVAIAssistant:
    """Gemini-API-based J-V analysis AI assistant"""

    def __init__(self, api_key: str, db_path: str = "jv_ai_history.db", model_name: str = None):
        self.api_key = api_key
        self.model_name = model_name or "gemini-2.0-flash"
        self.db_manager = JVDataManager(db_path)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Gemini init
        if GEMINI_AVAILABLE and api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(self.model_name)
            self.chat_session = None
        else:
            self.model = None
            self.chat_session = None

    def _get_system_prompt(self) -> str:
        """Build system prompt"""
        stats = self.db_manager.get_sample_statistics()

        return f"""You are an expert AI in solar-cell J-V characterization.

Role:
1. Analyze J-V curve data and detect anomalies
2. Extract equivalent-circuit parameters (Rs, Rsh, n, I0, Iph)
3. Recommend optimal experimental conditions
4. Generate an analysis report

Current database statistics:
- total samples: {stats.get('total_samples', 0)}
- avg PCE: {stats.get('avg_pce', 0):.2f}%
- max PCE: {stats.get('max_pce', 0):.2f}%
- avg Voc: {stats.get('avg_voc', 0):.3f} V
- avg Jsc: {stats.get('avg_jsc', 0):.2f} mA/cm²
- avg FF: {stats.get('avg_ff', 0):.2f}%

Follow these when responding:
- provide professional, accurate analysis
- give concrete numbers and rationale
- suggest improvements if any
- Respond in English
"""

    def _format_jv_data_for_prompt(self, data: Dict) -> str:
        """Convert J-V data to prompt text"""
        if isinstance(data, pd.DataFrame):
            # if a DataFrame
            text = "Sample data:\n"
            for _, row in data.iterrows():
                text += f"- {row.get('Filename', 'Unknown')}: "
                text += f"Voc={row.get('Voc V', 'N/A')}V, "
                text += f"Jsc={row.get('Jsc mA/cm2', 'N/A')}mA/cm², "
                text += f"FF={row.get('Fill Factor', 'N/A')}%, "
                text += f"PCE={row.get('PCE (%)', 'N/A')}%\n"
            return text
        elif isinstance(data, dict):
            # single sample
            return f"""Sample: {data.get('filename', 'Unknown')}
- Voc: {data.get('voc', 'N/A')} V
- Jsc: {data.get('jsc', 'N/A')} mA/cm²
- FF: {data.get('ff', 'N/A')} %
- PCE: {data.get('pce', 'N/A')} %"""
        else:
            return str(data)

    # -----------------------
    # 1. Anomaly Detection
    # -----------------------
    def detect_anomalies(self, samples_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Detect J-V curve anomalies
        - detect S-shape
        - shunt/series resistance anomalies
        - classify measurement error vs device defect
        """
        if not self.model:
            return {"error": "Gemini API not configured"}

        # store data (excluding duplicates)
        save_result = self.db_manager.save_batch_samples(samples_df)

        # precompute statistical outliers
        numeric_cols = ['Voc V', 'Jsc mA/cm2', 'Fill Factor', 'PCE (%)']
        anomaly_candidates = []

        for col in numeric_cols:
            if col in samples_df.columns:
                values = pd.to_numeric(samples_df[col], errors='coerce')
                mean_val = values.mean()
                std_val = values.std()

                # samples beyond 2 sigma
                outliers = samples_df[abs(values - mean_val) > 2 * std_val]
                for _, row in outliers.iterrows():
                    anomaly_candidates.append({
                        'filename': row.get('Filename', ''),
                        'parameter': col,
                        'value': row.get(col, ''),
                        'mean': mean_val,
                        'std': std_val
                    })

        # request Gemini analysis
        prompt = f"""{self._get_system_prompt()}

Analyze anomalies in the following J-V data:

{self._format_jv_data_for_prompt(samples_df)}

Statistical outlier candidates:
{json.dumps(anomaly_candidates, indent=2, ensure_ascii=False)}

Analysis items:
1. identify anomalous samples and reasons
2. possible causes (measurement error / device defect / process issue)
3. assess S-shape likelihood (based on low FF)
4. recommended actions

Respond in JSON format:
{{
    "anomalies": [
        {{
            "filename": "sample name",
            "issue": "issue type",
            "severity": "high/medium/low",
            "cause": "estimated cause",
            "recommendation": "recommended action"
        }}
    ],
    "summary": "overall summary",
    "quality_score": 0-100
}}
"""

        try:
            response = self.model.generate_content(prompt)
            result_text = response.text

            # try JSON parsing
            try:
                # extract JSON block
                if "```json" in result_text:
                    parts = result_text.split("```json")
                    if len(parts) > 1:
                        json_str = parts[1].split("```")[0]
                    else:
                        json_str = result_text
                elif "```" in result_text:
                    parts = result_text.split("```")
                    if len(parts) > 2:
                        json_str = parts[1]
                    else:
                        json_str = result_text
                else:
                    json_str = result_text

                result = json.loads(json_str.strip())
            except (json.JSONDecodeError, IndexError) as e:
                result = {"raw_response": result_text, "parse_error": str(e)}

            # store result
            self.db_manager.save_analysis_result(
                sample_hash="batch_" + datetime.now().strftime("%Y%m%d%H%M%S"),
                analysis_type="anomaly_detection",
                result=json.dumps(result, ensure_ascii=False)
            )

            result['data_saved'] = save_result
            return result

        except Exception as e:
            return {"error": str(e)}

    # -----------------------
    # 3. Equivalent Circuit Parameter Extraction
    # -----------------------
    def extract_circuit_parameters(self, sample_data: Dict,
                                    jv_curve: pd.DataFrame = None) -> Dict[str, Any]:
        """
        Extract equivalent-circuit parameters
        - Rs (series resistance)
        - Rsh (shunt resistance)
        - n (ideality factor)
        - I0 (reverse saturation current)
        - Iph (photogenerated current)
        """
        if not self.model:
            return {"error": "Gemini API not configured"}

        # prepare J-V curve data
        jv_info = ""
        if jv_curve is not None and not jv_curve.empty:
            # extract key points
            jv_info = f"\nJ-V curve data (partial):\n{jv_curve.head(20).to_string()}"

        prompt = f"""{self._get_system_prompt()}

Extract equivalent-circuit parameters for the following solar-cell sample:

{self._format_jv_data_for_prompt(sample_data)}
{jv_info}

Estimate the following parameters using the single-diode model:
1. Rs (series resistance, ohm*cm^2)
2. Rsh (shunt resistance, ohm*cm^2)
3. n (ideality factor)
4. I0 (reverse saturation current density, mA/cm^2)
5. Iph (photogenerated current density, mA/cm^2)

Estimation method:
- slope near Voc -> estimate Rs
- slope near 0V -> estimate Rsh
- Jsc ≈ Iph
- estimate n, I0 from the diode equation

Respond in JSON format:
{{
    "parameters": {{
        "Rs": {{"value": 0.0, "unit": "Ω·cm²", "confidence": "high/medium/low"}},
        "Rsh": {{"value": 0.0, "unit": "Ω·cm²", "confidence": "high/medium/low"}},
        "n": {{"value": 0.0, "unit": "", "confidence": "high/medium/low"}},
        "I0": {{"value": 0.0, "unit": "mA/cm²", "confidence": "high/medium/low"}},
        "Iph": {{"value": 0.0, "unit": "mA/cm²", "confidence": "high/medium/low"}}
    }},
    "analysis": "parameter interpretation",
    "improvement_suggestions": ["improvement suggestion 1", "improvement suggestion 2"]
}}
"""

        try:
            response = self.model.generate_content(prompt)
            result_text = response.text

            try:
                if "```json" in result_text:
                    parts = result_text.split("```json")
                    if len(parts) > 1:
                        json_str = parts[1].split("```")[0]
                    else:
                        json_str = result_text
                elif "```" in result_text:
                    parts = result_text.split("```")
                    if len(parts) > 2:
                        json_str = parts[1]
                    else:
                        json_str = result_text
                else:
                    json_str = result_text
                result = json.loads(json_str.strip())
            except (json.JSONDecodeError, IndexError) as e:
                result = {"raw_response": result_text, "parse_error": str(e)}

            # store
            is_new, data_hash = self.db_manager.save_sample(sample_data)
            self.db_manager.save_analysis_result(
                sample_hash=data_hash,
                analysis_type="circuit_parameters",
                result=json.dumps(result, ensure_ascii=False)
            )

            return result

        except Exception as e:
            return {"error": str(e)}

    # -----------------------
    # 4. Optimal Sample Recommendation
    # -----------------------
    def recommend_next_experiment(self, current_samples: pd.DataFrame,
                                   target_pce: float = None,
                                   constraints: Dict = None) -> Dict[str, Any]:
        """
        Recommend optimal experimental conditions
        - pattern analysis from historical data
        - suggest conditions to reach target PCE
        """
        if not self.model:
            return {"error": "Gemini API not configured"}

        # historical-data statistics
        historical_stats = self.db_manager.get_sample_statistics()
        historical_samples = self.db_manager.get_all_samples()

        # extract top-performing samples
        if not historical_samples.empty:
            top_samples = historical_samples.nlargest(5, 'pce')
            top_samples_info = top_samples.to_string()
        else:
            top_samples_info = "no historical data"

        target_info = f"Target PCE: {target_pce}%" if target_pce else "Goal: maximize PCE"
        constraint_info = json.dumps(constraints, ensure_ascii=False) if constraints else "no constraints"

        prompt = f"""{self._get_system_prompt()}

Based on current experimental data and history, recommend the next experimental conditions.

Current batch data:
{self._format_jv_data_for_prompt(current_samples)}

Best historical samples:
{top_samples_info}

{target_info}
Constraints: {constraint_info}

Analyze and recommend:
1. trend analysis of current data
2. identify key parameters for improvement
3. recommend conditions to try next
4. expected success probability

Respond in JSON format:
{{
    "trend_analysis": "current trend analysis",
    "key_factors": ["key factor 1", "key factor 2"],
    "recommendations": [
        {{
            "condition": "recommended condition",
            "expected_improvement": "expected improvement",
            "confidence": 0-100,
            "rationale": "rationale"
        }}
    ],
    "risk_factors": ["risk factor"],
    "next_priority": "top priority to try"
}}
"""

        try:
            response = self.model.generate_content(prompt)
            result_text = response.text

            try:
                if "```json" in result_text:
                    parts = result_text.split("```json")
                    if len(parts) > 1:
                        json_str = parts[1].split("```")[0]
                    else:
                        json_str = result_text
                elif "```" in result_text:
                    parts = result_text.split("```")
                    if len(parts) > 2:
                        json_str = parts[1]
                    else:
                        json_str = result_text
                else:
                    json_str = result_text
                result = json.loads(json_str.strip())
            except (json.JSONDecodeError, IndexError) as e:
                result = {"raw_response": result_text, "parse_error": str(e)}

            # store recommendation history
            with sqlite3.connect(self.db_manager.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO recommendations (context_hash, recommendation)
                    VALUES (?, ?)
                """, (
                    hashlib.md5(current_samples.to_json().encode()).hexdigest(),
                    json.dumps(result, ensure_ascii=False)
                ))
                conn.commit()

            return result

        except Exception as e:
            return {"error": str(e)}

    # -----------------------
    # 5. Natural Language Report Generation
    # -----------------------
    def generate_report(self, samples_df: pd.DataFrame,
                        report_type: str = "summary",
                        language: str = "en") -> Dict[str, Any]:
        """
        Generate a natural-language analysis report

        report_type:
        - "summary": brief summary
        - "detailed": detailed analysis
        - "comparison": comparison across samples
        - "publication": publication-style text
        """
        if not self.model:
            return {"error": "Gemini API not configured"}

        # store data
        save_result = self.db_manager.save_batch_samples(samples_df)

        report_instructions = {
            "summary": "Summarize the key results in 3-5 sentences.",
            "detailed": "Provide a detailed per-sample analysis and overall trends.",
            "comparison": "Compare performance differences across samples and analyze causes.",
            "publication": "Write objective, quantitative sentences suitable for an academic paper."
        }

        instruction = report_instructions.get(report_type, report_instructions["summary"])

        prompt = f"""{self._get_system_prompt()}

Write a report on the following J-V analysis data.

Data:
{self._format_jv_data_for_prompt(samples_df)}

Report type: {report_type}
Request: {instruction}

{"Write in Korean." if language == "ko" else "Please write in English."}

Respond in JSON format:
{{
    "title": "report title",
    "summary": "key summary (1-2 sentences)",
    "body": "body content",
    "highlights": ["key finding 1", "key finding 2"],
    "concerns": ["concern"],
    "recommendations": ["recommendation"]
}}
"""

        try:
            response = self.model.generate_content(prompt)
            result_text = response.text

            try:
                if "```json" in result_text:
                    parts = result_text.split("```json")
                    if len(parts) > 1:
                        json_str = parts[1].split("```")[0]
                    else:
                        json_str = result_text
                elif "```" in result_text:
                    parts = result_text.split("```")
                    if len(parts) > 2:
                        json_str = parts[1]
                    else:
                        json_str = result_text
                else:
                    json_str = result_text
                result = json.loads(json_str.strip())
            except (json.JSONDecodeError, IndexError) as e:
                result = {"raw_response": result_text, "parse_error": str(e)}

            # store
            self.db_manager.save_analysis_result(
                sample_hash="batch_" + datetime.now().strftime("%Y%m%d%H%M%S"),
                analysis_type=f"report_{report_type}",
                result=json.dumps(result, ensure_ascii=False)
            )

            result['data_saved'] = save_result
            return result

        except Exception as e:
            return {"error": str(e)}

    # -----------------------
    # Chat Function
    # -----------------------
    def start_chat(self):
        """Start a new chat session"""
        if not self.model:
            return False

        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.chat_session = self.model.start_chat(history=[])

        # set system context
        context = self._get_system_prompt()
        try:
            self.chat_session.send_message(context)
            return True
        except Exception as e:
            print(f"Chat session initialization error: {e}")
            return False

    def chat(self, user_message: str, include_data: pd.DataFrame = None) -> str:
        """
        Send a chat message and receive a response
        """
        if not self.model:
            return "Error: Gemini API not configured. Please set API key."

        # start a session if none
        if self.chat_session is None:
            self.start_chat()

        # add data context
        full_message = user_message
        if include_data is not None and not include_data.empty:
            full_message += f"\n\n[reference data]\n{self._format_jv_data_for_prompt(include_data)}"

        # store message
        self.db_manager.save_chat_message(self.session_id, "user", user_message)

        try:
            response = self.chat_session.send_message(full_message)
            assistant_message = response.text

            # store response
            self.db_manager.save_chat_message(self.session_id, "assistant", assistant_message)

            return assistant_message

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            self.db_manager.save_chat_message(self.session_id, "error", error_msg)
            return error_msg

    def get_chat_history(self) -> List[Dict]:
        """Query the current session's chat history"""
        return self.db_manager.get_chat_history(self.session_id)

    # -----------------------
    # Quick Analysis (integrated)
    # -----------------------
    def quick_analysis(self, samples_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Quick integrated analysis - run all features at once
        """
        # check API init
        if not self.model:
            return {"error": "Gemini API not configured. Please set API key."}

        if samples_df is None or samples_df.empty:
            return {"error": "No data to analyze."}

        results = {
            'timestamp': datetime.now().isoformat(),
            'sample_count': len(samples_df)
        }

        try:
            # 1. store data
            results['data_saved'] = self.db_manager.save_batch_samples(samples_df)
            print(f"[Quick Analysis] Data saved: {results['data_saved']}")

            # 2. brief report
            print("[Quick Analysis] Generating summary report...")
            report = self.generate_report(samples_df, report_type="summary")
            if 'error' in report:
                results['summary'] = f"Report error: {report['error']}"
            else:
                results['summary'] = report.get('summary', report.get('body', report.get('raw_response', '')))
            print(f"[Quick Analysis] Summary: {results['summary'][:100] if results['summary'] else 'Empty'}...")

            # 3. anomaly detection (brief)
            print("[Quick Analysis] Detecting anomalies...")
            anomalies = self.detect_anomalies(samples_df)
            if 'error' in anomalies:
                results['anomalies'] = []
                results['quality_score'] = None
                print(f"[Quick Analysis] Anomaly detection error: {anomalies['error']}")
            else:
                results['anomalies'] = anomalies.get('anomalies', [])[:3]  # top 3 only
                results['quality_score'] = anomalies.get('quality_score', None)
                print(f"[Quick Analysis] Found {len(results['anomalies'])} anomalies, Quality: {results['quality_score']}")

            # 4. recommendation (brief)
            print("[Quick Analysis] Getting recommendations...")
            recommendations = self.recommend_next_experiment(samples_df)
            if 'error' in recommendations:
                results['next_priority'] = f"Recommendation error: {recommendations['error']}"
            else:
                results['next_priority'] = recommendations.get('next_priority', '')
            print(f"[Quick Analysis] Recommendation: {results['next_priority'][:100] if results['next_priority'] else 'Empty'}...")

        except Exception as e:
            print(f"[Quick Analysis] Exception: {e}")
            results['error'] = str(e)

        return results


# =========================
# Integration with run_jv.py
# =========================
class JVAIIntegration:
    """Wrapper class for integration with run_jv.py"""

    def __init__(self, api_key: str = "", db_path: str = "jv_ai_history.db"):
        self.assistant = None
        self.api_key = api_key
        self.db_path = db_path
        self.model_name = ""
        self._initialized = False

    def initialize(self, api_key: str = None, model_name: str = None):
        """Initialize with API key"""
        if api_key:
            self.api_key = api_key
        if model_name:
            self.model_name = model_name

        if self.api_key:
            self.assistant = JVAIAssistant(self.api_key, self.db_path, model_name=self.model_name)
            self._initialized = True
            return True
        return False

    def is_ready(self) -> bool:
        """Availability"""
        return self._initialized and self.assistant is not None

    def analyze_processed_data(self, processed_data: Dict) -> Dict[str, Any]:
        """
        Analyze process_jv_directory() results
        """
        if not self.is_ready():
            return {"error": "AI Assistant not initialized. Please configure API key."}

        if processed_data is None:
            return {"error": "No processed data provided"}

        # extract best_performance DataFrame
        best_df = processed_data.get('best_performance', pd.DataFrame())

        if best_df is None or (hasattr(best_df, 'empty') and best_df.empty):
            return {"error": "No best_performance data found"}

        print(f"[AI Integration] Analyzing {len(best_df)} samples...")
        return self.assistant.quick_analysis(best_df)

    def get_report(self, processed_data: Dict, report_type: str = "summary") -> str:
        """Return report text"""
        if not self.is_ready():
            return "AI Assistant not initialized. Please set API key."

        best_df = processed_data.get('best_performance', pd.DataFrame())

        if best_df.empty:
            return "No data to analyze."

        result = self.assistant.generate_report(best_df, report_type)

        if 'error' in result:
            return f"Error: {result['error']}"

        # format report
        report_text = ""
        if 'title' in result:
            report_text += f"# {result['title']}\n\n"
        if 'summary' in result:
            report_text += f"{result['summary']}\n\n"
        if 'body' in result:
            report_text += f"{result['body']}\n\n"
        if 'highlights' in result:
            report_text += "## Key findings\n"
            for h in result['highlights']:
                report_text += f"- {h}\n"
        if 'recommendations' in result:
            report_text += "\n## Recommendations\n"
            for r in result['recommendations']:
                report_text += f"- {r}\n"

        return report_text if report_text else result.get('raw_response', str(result))

    def chat(self, message: str, context_data: Dict = None) -> str:
        """Chat interface"""
        if not self.is_ready():
            return "AI Assistant not initialized. Please set API key."

        include_data = None
        if context_data:
            include_data = context_data.get('best_performance', pd.DataFrame())

        return self.assistant.chat(message, include_data)

    def get_statistics(self) -> Dict[str, Any]:
        """Stored-data statistics"""
        if not self.is_ready():
            return {"error": "AI Assistant not initialized"}

        return self.assistant.db_manager.get_sample_statistics()


# =========================
# Standalone Test
# =========================
def main():
    """Main function for testing"""
    print("=" * 50)
    print("J-V AI Assistant - Test Mode")
    print("=" * 50)

    # enter API key
    api_key = input("Enter Gemini API Key (or press Enter to skip): ").strip()

    if not api_key:
        print("\nNo API key provided. Testing database functions only...")

        # DB test
        db = JVDataManager("test_jv_ai.db")

        # test data
        test_samples = pd.DataFrame([
            {'Filename': 'Sample_A', 'Voc V': 1.05, 'Jsc mA/cm2': 22.5, 'Fill Factor': 75.2, 'PCE (%)': 17.8},
            {'Filename': 'Sample_B', 'Voc V': 1.08, 'Jsc mA/cm2': 23.1, 'Fill Factor': 78.5, 'PCE (%)': 19.5},
            {'Filename': 'Sample_C', 'Voc V': 0.95, 'Jsc mA/cm2': 21.0, 'Fill Factor': 65.0, 'PCE (%)': 13.0},
        ])

        result = db.save_batch_samples(test_samples)
        print(f"\nSaved: {result}")

        stats = db.get_sample_statistics()
        print(f"Statistics: {stats}")

        all_samples = db.get_all_samples()
        print(f"\nAll samples:\n{all_samples}")

    else:
        # full test
        assistant = JVAIAssistant(api_key)

        # test data
        test_samples = pd.DataFrame([
            {'Filename': 'Sample_A', 'Voc V': 1.05, 'Jsc mA/cm2': 22.5, 'Fill Factor': 75.2, 'PCE (%)': 17.8},
            {'Filename': 'Sample_B', 'Voc V': 1.08, 'Jsc mA/cm2': 23.1, 'Fill Factor': 78.5, 'PCE (%)': 19.5},
            {'Filename': 'Sample_C', 'Voc V': 0.95, 'Jsc mA/cm2': 21.0, 'Fill Factor': 65.0, 'PCE (%)': 13.0},
        ])

        print("\n[1] Quick Analysis...")
        result = assistant.quick_analysis(test_samples)
        print(json.dumps(result, indent=2, ensure_ascii=False))

        print("\n[2] Chat Test...")
        assistant.start_chat()
        response = assistant.chat("Analyze the cause of Sample_C low performance", test_samples)
        print(f"AI: {response}")

        print("\n[3] Interactive Chat (type 'quit' to exit)...")
        while True:
            user_input = input("\nYou: ").strip()
            if user_input.lower() in ['quit', 'exit', 'q']:
                break
            response = assistant.chat(user_input)
            print(f"AI: {response}")

    print("\nTest completed.")


if __name__ == "__main__":
    main()
