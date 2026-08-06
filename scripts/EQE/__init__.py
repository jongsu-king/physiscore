"""EQE analysis package.

The GUI module is deliberately NOT imported here. Importing it eagerly pulls
tkinter, customtkinter and the matplotlib Tk backend into every consumer, which
makes the analysis code impossible to use headlessly -- in tests, batch jobs or
notebooks. Import the specific module you need instead:

    # NOTE: EQE has no separate core module yet -- its physics still
    # lives inside run_eqe.py and therefore still requires a GUI stack.
    from scripts.EQE import run_eqe       # GUI window
"""
