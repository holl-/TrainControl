import threading

from fpme import dash_app, matplotlib_app, trains

trains.start()

threading.Thread(target=lambda: dash_app.app.run_server(debug=True, host='0.0.0.0', port=trains.CONFIG['server-port'], use_reloader=False)).start()

matplotlib_app.show()
