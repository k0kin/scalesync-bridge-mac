import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from scalesync_bridge.main import main
    main()
except KeyboardInterrupt:
    print("\nBridge stopped by user.")
except Exception:
    traceback.print_exc()
    print("\n[ERROR] Bridge crashed unexpectedly. See error above.")
    try:
        input("Press Enter to close this window...")
    except EOFError:
        pass
