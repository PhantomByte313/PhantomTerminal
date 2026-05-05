#!/usr/bin/env python3
"""
VSCode Terminal Emulator - Professional Grade
Entry point for the application.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    """Main entry point."""
    try:
        from ui.app import TerminalApp
        app = TerminalApp()
        app.run()
    except ImportError as e:
        print(f"Error: Missing dependency - {e}")
        print("Please install requirements: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
