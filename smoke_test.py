"""
smoke_test.py
Verifies the integrity of the BrainzMRI Refactor (Phase 2).
Checks for circular imports, config loading, and class duplication.
"""

import sys
import os
import inspect

def print_pass(msg):
    print(f"[PASS] {msg}")

def print_fail(msg):
    print(f"[FAIL] {msg}")

def run_test():
    print("=== BrainzMRI Phase 2 Smoke Test ===\n")

    # 1. Module Import Check
    print("--- 1. Module Import Integrity ---")
    modules = [
        "api_client", "config", "enrichment", "gui_charts", "gui_main",
        "gui_tableview", "gui_user_editor", "parsing", "report_engine",
        "reporting", "sync_engine", "user"
    ]
    
    for mod_name in modules:
        try:
            __import__(mod_name)
            print_pass(f"Module '{mod_name}' imported successfully.")
        except ImportError as e:
            print_fail(f"Could not import '{mod_name}': {e}")
            return
        except Exception as e:
            print_fail(f"Error during import of '{mod_name}': {e}")
            return

    # 2. Configuration Check
    print("\n--- 2. Configuration Singleton ---")
    try:
        from config import config
        if config.app_root and os.path.exists(config.app_root):
            print_pass(f"Config loaded. App Root: {config.app_root}")
        else:
            print_fail("Config load failed or app_root is invalid.")
            
        if hasattr(config, "network_delay"):
            print_pass(f"Network Delay setting found: {config.network_delay}s")
        else:
            print_fail("Config missing 'network_delay' attribute.")
    except Exception as e:
        print_fail(f"Config test failed: {e}")

    # 3. Sync Engine Separation Check
    print("\n--- 3. Sync Logic Decoupling ---")
    try:
        import gui_main
        import sync_engine
        
        # Verify gui_main is using the class from sync_engine, not a local copy
        if hasattr(gui_main, "SyncManager"):
            gui_sync = gui_main.SyncManager
            eng_sync = sync_engine.SyncManager
            
            if gui_sync is eng_sync:
                print_pass("gui_main.py is correctly importing SyncManager from sync_engine.")
            else:
                print_fail("gui_main.py has a DUPLICATE definition of SyncManager. (Check file content!)")
        else:
            print_fail("SyncManager not found in gui_main namespace.")

        # Verify ProgressWindow import
        if hasattr(gui_main, "ProgressWindow"):
            if gui_main.ProgressWindow is sync_engine.ProgressWindow:
                print_pass("gui_main.py is correctly importing ProgressWindow from sync_engine.")
            else:
                print_fail("gui_main.py has a DUPLICATE definition of ProgressWindow.")
                
    except Exception as e:
        print_fail(f"Sync separation check failed: {e}")

    # 4. GUI Main Class Integrity
    print("\n--- 4. GUI Main Class Integrity ---")
    try:
        if hasattr(gui_main, "BrainzMRIGUI"):
            # Check for the methods that were missing earlier
            cls = gui_main.BrainzMRIGUI
            if hasattr(cls, "save_report") and callable(cls.save_report):
                print_pass("BrainzMRIGUI.save_report method exists.")
            else:
                print_fail("BrainzMRIGUI.save_report method is MISSING.")
                
            if hasattr(cls, "show_graph") and callable(cls.show_graph):
                print_pass("BrainzMRIGUI.show_graph method exists.")
            else:
                print_fail("BrainzMRIGUI.show_graph method is MISSING.")
        else:
            print_fail("BrainzMRIGUI class not found in gui_main.")
    except Exception as e:
        print_fail(f"Class integrity check failed: {e}")

    print("\n=== Test Complete ===")

if __name__ == "__main__":
    run_test()