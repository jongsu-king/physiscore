"""XRD analysis package.

The GUI module is deliberately NOT imported here. Importing it eagerly pulls
tkinter, customtkinter and the matplotlib Tk backend into every consumer, which
makes the analysis code impossible to use headlessly -- in tests, batch jobs or
notebooks. Import the specific module you need instead:

    from scripts.XRD import xrd_core      # analysis core, no GUI
    from scripts.XRD import run_xrd       # GUI window
"""
