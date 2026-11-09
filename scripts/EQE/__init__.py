"""EQE analysis package.

The GUI module is deliberately NOT imported here: importing it pulls tkinter,
customtkinter and the matplotlib Tk backend into every consumer. Import the
module you need:

    from scripts.EQE import eqe_core      # physics, GUI-free (Jsc, Eg, Urbach, detailed balance)
    from scripts.EQE import run_eqe       # GUI window
"""
