import threading
import time

from fpme import dash_app, matplotlib_app


threading.Thread(target=lambda: dash_app.app.run_server(debug=True, host='0.0.0.0', port=8051, use_reloader=False)).start()

matplotlib_app.plt.show()
