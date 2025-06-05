import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from measurement_client.client import main

if __name__ == "__main__":
    main()
