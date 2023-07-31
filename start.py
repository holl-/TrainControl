import sys
import os
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from fpme import dash_app

if __name__ == '__main__':
    dash_app.start()
