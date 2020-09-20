import threading

from fpme import dash_app, matplotlib_app, logic

logic.start()

threading.Thread(target=lambda: dash_app.app.run_server(debug=True, host='0.0.0.0', port=logic.CONFIG['server-port'], use_reloader=False)).start()

matplotlib_app.plt.show()
