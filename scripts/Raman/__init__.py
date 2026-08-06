"""Raman analysis package.

The GUI module is deliberately NOT imported here. Importing it eagerly pulls
tkinter, customtkinter and the matplotlib Tk backend into every consumer, which
makes the analysis code impossible to use headlessly -- in tests, batch jobs or
notebooks. Import the specific module you need instead:

    from scripts.Raman import raman_core      # analysis core, no GUI
    from scripts.Raman import run_raman       # GUI window
"""
