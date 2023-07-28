import os
import time
from typing import Dict, Optional

from flask import request
import dash
from dash import html, dcc
import dash_bootstrap_components as dbc
import dash_daq as daq
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate
from dash import callback_context

from fpme import trains, switches, signal_gen


class Client:
    PING_TIME = 2.0  # Max time between main updates
    GLOBAL_ID_COUNTER = 0
    APP_INSTANCE_ID = int(time.time())

    def __init__(self, addr, user_id=None, admin=False, local=False):
        self.addr = addr  # IP
        if user_id is None:
            self.user_id = f'{Client.APP_INSTANCE_ID}-{Client.GLOBAL_ID_COUNTER}'  # generated after website loaded, stored in 'user-id' div component
            Client.GLOBAL_ID_COUNTER += 1
        else:
            self.user_id = user_id
        self.train = None
        self.last_input_perf_counter = time.perf_counter()
        self.is_admin = admin
        self.is_local = local

    def __repr__(self):
        return f"{self.user_id} @ {self.addr if not self.is_local else 'localhost'}{' (Admin)' if self.is_admin else ''} controlling {self.train}"

    def is_inactive(self):
        return time.perf_counter() - self.last_input_perf_counter > Client.PING_TIME * 2.5


CLIENTS: Dict[str, Client] = {}  # id -> Client


def get_client(user_id: str or None, admin=None, local=None, register_heartbeat=True) -> Client:
    """
    Args:
        user_id: if `str`, looks up or creates a client with the given ID, if `None`, generates a new ID.
    """
    if user_id == 'id':  # not initialized
        raise PreventUpdate
    if user_id in CLIENTS:
        client = CLIENTS[user_id]
        if register_heartbeat:
            client.last_input_perf_counter = time.perf_counter()
        return client
    else:
        client = Client(request.remote_addr, user_id, False if admin is None else admin, False if local is None else local)
        print(f"Registered client {client}")
        CLIENTS[client.user_id] = client
        return client


def clear_inactive_clients():
    for client in tuple(CLIENTS.values()):
        if client.is_inactive():
            del CLIENTS[client.user_id]
            if client.train is not None:
                client.train.set_target_speed(0)


app = dash.Dash('Modelleisenbahn', external_stylesheets=[dbc.themes.BOOTSTRAP, 'slider.css'], title='Modelleisenbahn', update_title=None)

with open('../welcome_text.md') as file:
    welcome_text = file.read()
welcome_layout = html.Div(id='welcome', children=[
    dcc.Markdown(welcome_text),
])


def build_control():
    return html.Div(style={}, children=[
        html.Div(style={'display': 'inline-block', 'width': 100, 'height': 280, 'vertical-align': 'top'}, children=[
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '40%'}, children=[
                html.Button('⌁', id='power-on', style={'width': '100%', 'height': '100%', 'font-size': '66px'}, disabled=True),  # ⌁⚡
            ]),
            html.Div([], style={'width': 1, 'height': 10}),
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '60%'}, children=[
                html.Button('⚠', id='power-off', style={'width': '100%', 'height': '100%', 'font-size': '58px', 'background-color': '#cc0000', 'color': 'white'}),
            ]),
        ]),
        html.Div([], style={'display': 'inline-block', 'width': 40, 'height': 1, 'vertical-align': 'top'}),
        html.Div(style={'display': 'inline-block', 'vertical-align': 'top', 'height': 290}, children=[
            html.Div(style={'width': '100%', 'height': '100%', 'position': 'relative'}, children=[
                html.Div(style={'width': '100%', 'height': '100%', 'overflow': 'hidden'}, children=[
                    daq.Gauge(id='speed', value=0, label='Zug - Richtung', max=250, min=0, units='km/h', showCurrentValue=False, size=280),
                ]),
                html.Img(src=f'assets/?.png', id='train-image', style={}),
            ]),
        ]),
        html.Div(style={'display': 'inline-block', 'width': 60, 'height': 310, 'vertical-align': 'top'}, children=[
            dcc.Slider(id='speed-control', min=0, max=10, step=None, value=0, marks={0: '', 100: '', 200: ''}, updatemode='drag', vertical=True, verticalHeight=310),
        ]),
        html.Div(style={'display': 'inline-block', 'width': 140, 'height': 300, 'vertical-align': 'top'}, children=[
            html.Div(style={'display': 'inline-block', 'width': '50%', 'height': '16%'}, children=[
                html.Button('-', id='decelerate1', style={'width': '100%', 'height': '100%', 'background-color': '#499936', 'color': 'white'}),
            ]),
            html.Div(style={'display': 'inline-block', 'width': '50%', 'height': '16%'}, children=[
                html.Button('+', id='accelerate1', style={'width': '100%', 'height': '100%', 'background-color': '#499936', 'color': 'white'}),
            ]),
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '20%'}, children=[
                html.Button('◄ ►', id='reverse', style={'width': '100%', 'height': '100%'}),  # , 'background-color': '#A0A0FF', 'color': 'white'
            ]),
            html.Div(style={'display': 'inline-block', 'width': 1, 'height': '1%'}, children=[]),
            "Weichen: ",
            # html.Div("➞", style={'display': 'inline-block'}),
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '15%'}, children=[  # setting width/height adds spacing above
                html.Button('↑', id='set-switches-C', style={'width': '33%', 'height': '100%'}),
                html.Button('⬈', id='set-switches-B', style={'width': '33%', 'height': '100%'}),
                html.Button('➞', id='set-switches-A', style={'width': '33%', 'height': '100%'}),
            ]),
            html.Div(style={'display': 'inline-block', 'width': 1, 'height': '1%'}, children=[]),
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '30%'}, children=[
                html.Button('🛑', id='stop-train', style={'width': '100%', 'height': '100%', 'font-size': '48px', 'background-color': '#FF8000', 'color': 'white'}),  # ⛔
            ]),
        ]),
        dcc.Store('target-speed-store', data=0),
        dcc.Store('acceleration-store', data=0),
        dcc.Store('needle-velocity', data=0),
    ])

switch_trains = html.Div([
    html.Div([], style={'display': 'inline-block', 'width': 20, 'height': 10}),
    *[html.Button([html.Img(src=f'assets/{train.image_path}', style={d: s for d, s in zip(['width', 'height'], train.fit_image_size(60, 20))}), train.name], id=f'switch-to-{train.name}', disabled=True) for train in trains.TRAINS],
    html.Div([], style={'display': 'inline-block', 'width': 10, 'height': 10}),
    html.Button("🚪⬏", id='release-train', disabled=True)  # Aussteigen
])
# disable button when train in use
TRAIN_BUTTONS = [Input(f'switch-to-{train.name}', 'n_clicks') for train in trains.TRAINS]


admin_controls = [
    html.Button("Beenden", id='admin-kill'),
    dcc.Markdown("# Status", id='admin-status'),
    dcc.Checklist(id='admin-checklist', labelStyle=dict(display='block'), options=[
        {'label': "Max 120 km/h", 'value': 'global-speed-limit'},
        {'label': "Züge haben Wagen", 'value': 'train-cars'},
        # {'label': "Fahrplan-Modus (Nur benötigte Weichen schalten)", 'value': 'schedule-mode'},
        {'label': "Weichen sperren", 'value': 'lock-all-switches'},
        {'label': "Lichter an", 'value': 'lights-on'},
    ]),
]
for train in trains.TRAINS:
    admin_controls.append(html.Div(style={'width': '80%'}, children=[
        html.Div(train.name, style={'display': 'inline-block', 'width': 90}),
        html.Button('🛑', id=f'admin-stop-{train}', style={'width': 50}),
        html.Div(style={'display': 'inline-block', 'width': 100}, children=[
            dbc.Progress(id=f'admin-speedometer-{train.name}', value=0.5, max=1),
        ]),
        html.Div(style={'display': 'inline-block', 'width': 80}, children=[
            dcc.Checklist(id=f'admin-lock-{train}', options=[{'label': "Sperren", 'value': f'admin-disable-{train}'}])
        ]),
        html.Button('🚪⬏', id=f'admin-kick-{train}', style={'width': 50}),
        " ",
        html.Div("...", id=f'admin-train-status-{train.name}', style={'display': 'inline-block', 'width': 200}),
    ]))
admin_controls.append(html.Div(style={'height': 60, 'width': 300}, children=[
    html.Div(style={'display': 'inline-block', 'width': '50%', 'height': '100%'}, children=[
        html.Button('⌁', id='power-on-admin', style={'width': '100%', 'height': '100%'}),
    ]),
    html.Div(style={'display': 'inline-block', 'width': '50%', 'height': '100%'}, children=[
        html.Button('⚠', id='power-off-admin', style={'width': '100%', 'height': '100%', 'background-color': '#cc0000', 'color': 'white'}),
    ]),
]))

control_layout = html.Div(id='control', style={'display': 'none'}, children=[
    build_control(),
    html.Div(id='stop-train-placeholder', style={'display': 'none'}),
])


app.layout = html.Div(children=[
    dcc.Location(id='url', refresh=False),
    dcc.Interval(id='main-update', interval=Client.PING_TIME * 1000),
    dcc.Interval('client-interval', interval=1000 / 20),
    dcc.Store(id='power-status-store', data=False),
    html.Div('id', id='user-id', style={'display': 'none'}),
    html.Div([], id='admin-controls'),
    welcome_layout,
    switch_trains,
    control_layout,
])
app.config.suppress_callback_exceptions = True


@app.callback([Output('user-id', 'children'),
               Output('admin-controls', 'children')],
              [Input('url', 'pathname')], [State('url', 'href')])
def on_page_load(path, href):
    if path:
        new_client = get_client(None, admin=path == '/admin', local=href.startswith('http://localhost') or request.remote_addr in [LOCAL_IP, '127.0.0.1'])
        return new_client.user_id, admin_controls if new_client.is_admin else []
    else:
        raise PreventUpdate()


@app.callback(Output('welcome', 'style'), TRAIN_BUTTONS)
def hide_welcome(*n_clicks):
    if any(n_clicks):
        return {'display': 'none'}
    raise PreventUpdate()


@app.callback([Output('control', 'style'), Output('speed', 'label'),
               *[Output(f'switch-to-{train.name}', 'disabled') for train in trains.TRAINS],
               Output('release-train', 'disabled'),
               Output('power-on', 'disabled'),
               Output('speed', 'max'), Output('speed', 'color'),
               Output('speed-control', 'max'), Output('speed-control', 'marks'),  # Speedometer settings
               Output('power-status-store', 'data'),
               Output('acceleration-store', 'data'),
               Output('train-image', 'src'), Output('train-image', 'style'),
               Output('set-switches-C', 'disabled'), Output('set-switches-B', 'disabled'), Output('set-switches-A', 'disabled'), ],
              [Input('user-id', 'children'), Input('main-update', 'n_intervals'),
               Input('power-off', 'n_clicks'), Input('power-on', 'n_clicks'),
               Input('reverse', 'n_clicks'),
               Input('set-switches-C', 'n_clicks'), Input('set-switches-B', 'n_clicks'), Input('set-switches-A', 'n_clicks'),
               Input('release-train', 'n_clicks'), *TRAIN_BUTTONS],)
def main_update(user_id, *args):
    trigger = callback_context.triggered[0]
    trigger_id, trigger_prop = trigger["prop_id"].split(".")
    client = get_client(user_id)
    clear_inactive_clients()
    is_admin = client.is_admin

    if client.train is not None and client.train.admin_only and not is_admin:
        client.train = None

    # Button actions
    if trigger_id == 'power-off':
        trains.power_off()
    elif trigger_id == 'power-on':
        trains.power_on()
        time.sleep(0.2)
    elif trigger_id.startswith('switch-to-'):
        if client.train is None or client.train.is_parked:
            new_train_name = trigger_id[len('switch-to-'):]
            new_train = trains.get_by_name(new_train_name)
            if all([c.train != new_train for c in CLIENTS.values()]):  # train not in use
                if client.train is not None:
                    client.train.set_target_speed(0)  # Stop the train we're exiting
                client.train = new_train
    elif trigger_id == 'release-train' and client.train is not None:
        if client.train:
            client.train.set_target_speed(0)
            client.train = None
    elif trigger_id == 'reverse':
        if client.train:
            client.train.reverse()
    elif trigger_id.startswith('set-switches-'):
        track = trigger_id[len('set-switches-'):]
        if client.train:
            if switches.can_set(incoming=get_incoming(client.train), track=track, ignore_lock=is_admin):
                switches.set_switches(incoming=get_incoming(client.train), track=track)

    # Gather info to display
    if client.train is None:
        label = " "
    else:
        # train_name = f"{client.train.name}"  # {client.train.icon}
        label = client.train.name  # "◀ " + train_name if client.train.in_reverse else train_name + " ▶"
    if not trains.is_power_on():
        label += " ⚡"  # Kein Strom  ⚡⌁

    if client.train is not None and not client.train.is_parked and not is_admin:
        blocked_trains = [True] * len(trains.TRAINS)
        release_disabled = True
    else:
        blocked_trains = [(train.admin_only and not is_admin) or any([client.train == train for client in CLIENTS.values()]) for train in trains.TRAINS]
        release_disabled = client.train is None and not is_admin

    power_on_disabled = time.perf_counter() - trains.POWER_OFF_TIME < 5 or trains.is_power_on()

    max_speed = int(round(client.train.max_speed)) if client.train else 1
    # color = {'gradient': True, 'ranges': {'green': [0, .6 * max_speed], 'yellow': [.6 * max_speed, .8 * max_speed], 'red': [.8 * max_speed, max_speed]}} if trains.is_power_on() else 'blue'
    color = 'green' if trains.is_power_on() else 'blue'
    if client.train:
        marks = {speed: '' for speed in client.train.speeds}
        marks[0] = '0'
        marks[client.train.speeds[-1]] = str(int(client.train.speeds[-1]))
    else:
        marks = {}

    incoming = get_incoming(client.train) if client.train else 'Any'

    if client.train:
        image = f"assets/{client.train.directional_image_path}"
        w, h = client.train.fit_image_size(120, 40)
        image_style = {'width': w, 'height': h, 'position': 'absolute', 'top': '90%', 'left': 290/2 - w/2 + 10}
        if client.train.in_reverse:
            image_style.update({'-webkit-transform': 'scaleX(-1)', 'transform': 'scaleX(-1)'})
    else:
        image = '?'
        image_style = {}

    return [
        ({} if client.train is not None else {'display': 'none'}),
        label,
        *blocked_trains,
        release_disabled,
        power_on_disabled,
        max_speed,
        color,
        max_speed,
        marks,
        trains.is_power_on(),
        client.train.acceleration if client.train else -1.,
        image, image_style,
        not (switches.can_set(incoming, 'C') or is_admin), not (switches.can_set(incoming, 'B') or is_admin), not (switches.can_set(incoming, 'A') or is_admin)
    ]


app.clientside_callback(
    """
    function(n, speed_, last_acceleration, target_with_power, target_acceleration, dt, has_power) {
        if(Number(target_with_power) === target_with_power) {  // Real update
            let speed = isNaN(speed_) ? 0 : speed_;
            let target = has_power ? target_with_power : -1;
            if(target < 0) {
                return [Math.max(0, speed * Math.pow(0.2, dt/1000) - 2 * target_acceleration * dt / 1000), - 2 * target_acceleration];
            }
            direction = target > speed ? 1 : -1
            var eff_acceleration = last_acceleration;
            if(Math.abs(speed - target) > 0.1) {
                eff_acceleration += (target_acceleration * direction - last_acceleration) * dt / 1000 * 2;
            }
            if(target_acceleration > last_acceleration) {
                eff_acceleration = Math.min(eff_acceleration, target_acceleration);
            } else {
                eff_acceleration = Math.max(eff_acceleration, target_acceleration);
            }
            if(Math.abs(speed - target) < 30) {
                eff_acceleration *= Math.pow(Math.abs(speed - target) / 30 * 10 / target_acceleration, dt / 1000)
            }
            
            var new_speed = speed + eff_acceleration * dt / 1000 * (1.5 - 0.5 * direction)
            if(new_speed < 0) {
                new_speed = 0
                eff_acceleration = 0
            }
            
            if(target > speed) {
                return [new_speed, eff_acceleration];
            }
            else {
                return [new_speed, eff_acceleration];
            }
        }
        else {  // Initialization
            return [0, 0];
        }
    }
    """,
    [Output('speed', 'value'), Output('needle-velocity', 'data')],
    [Input('client-interval', 'n_intervals')],  # Input('target-speed-store', 'modified_timestamp')
    [State('speed', 'value'), State('needle-velocity', 'data'), State('target-speed-store', 'data'), State('acceleration-store', 'data'), State('client-interval', 'interval'), State('power-status-store', 'data')]
)


@app.callback([Output('target-speed-store', 'data'), Output('reverse', 'disabled')],
              [Input('speed-control', 'value')],
              [State('user-id', 'children')])
def speed_update(target_speed, user_id):
    client = get_client(user_id)
    trigger = callback_context.triggered[0]
    trigger_id, trigger_prop = trigger["prop_id"].split(".")
    if trigger_id == 'speed-control':
        if client.train:
            client.train.set_target_speed(-target_speed if client.train.in_reverse else target_speed)
    if client.train and client.train.is_emergency_stopping:
        return -1, False
    if client.train:
        return abs(client.train.target_speed), client.train.target_speed != 0
    else:
        return -1, True


@app.callback(Output('speed-control', 'value'),
              [Input('accelerate1', 'n_clicks'), Input('decelerate1', 'n_clicks'), Input('stop-train', 'n_clicks')],
              [State('user-id', 'children')])
def on_speed_button_pressed(*args):
    client = get_client(args[-1])
    trigger = callback_context.triggered[0]
    trigger_id, trigger_prop = trigger["prop_id"].split(".")
    if trigger_id == 'accelerate1':
        if client.train:
            client.train.accelerate(1)
    elif trigger_id == 'decelerate1':
        if client.train:
            client.train.accelerate(-1)
    elif trigger_id == 'stop-train':
        if client.train:
            client.train.emergency_stop()
    return abs(client.train.target_speed) if client.train else 0


# Admin Controls


@app.callback([Output('admin-status', 'children'),
               *[Output(f'admin-speedometer-{train.name}', 'value') for train in trains.TRAINS],
               *[Output(f'admin-train-status-{train.name}', 'children') for train in trains.TRAINS]],
              [Input('main-update', 'n_intervals'),
               Input('admin-checklist', 'value'),
               Input('power-off-admin', 'n_clicks'),
               Input('power-on-admin', 'n_clicks'),
               Input('admin-kill', 'n_clicks'),
               *[Input(f'admin-stop-{train}', 'n_clicks') for train in trains.TRAINS],
               *[Input(f'admin-kick-{train}', 'n_clicks') for train in trains.TRAINS],
               ])
def admin_update(_n, checklist, *args):
    trigger = callback_context.triggered[0]
    trigger_id, trigger_prop = trigger["prop_id"].split(".")
    if trigger_id == 'admin-kill':
        trains.destroy()
        time.sleep(.5)
        os._exit(0)
    elif trigger_id == 'power-off-admin':
        trains.power_off()
    elif trigger_id == 'power-on-admin':
        trains.power_on()
    elif trigger_id.startswith('admin-stop-'):
        train = trains.get_by_name(trigger_id[len('admin-stop-'):])
        train.emergency_stop()
    elif trigger_id == 'admin-checklist':
        switches.set_all_locked('lock-all-switches' in checklist)
        trains.set_global_speed_limit(120 if 'global-speed-limit' in checklist else None)
        trains.set_train_cars_connected('train-cars' in checklist)
        global _SCHEDULE_MODE
        _SCHEDULE_MODE = 'schedule-mode' in checklist

    elif trigger_id.startswith('admin-kick-'):
        train = trains.get_by_name(trigger_id[len('admin-kick-'):])
        for client in CLIENTS.values():
            if client.train == train:
                train.set_target_speed(0)
                print("Breaking")
                client.train = None
                break
    if SERIAL_PORT is None:
        signal_status = "⛔ Port not configured"
    elif trains.GENERATOR.has_error:
        signal_status = f"⛔ {trains.GENERATOR.error_message}"
    elif trains.GENERATOR.is_short_circuited:
        signal_status = '⚠ short-circuited'
    elif trains.is_power_on():
        signal_status = '✅'
    else:
        signal_status = '⚠'
    status = f"""
* Server: {LOCAL_IP}:{PORT}
* {"Switches: ✅ online." if RELAY_ERR is None else f"Switches: ⛔ {RELAY_ERR}"}
* Signal: {signal_status}
"""
    return [status, *[abs(train.target_speed) / train.max_speed for train in trains.TRAINS],
            *[status_str(train) for train in trains.TRAINS]]


def status_str(train: trains.Train):
    label = "◀" if train.in_reverse else "▶"
    if train.admin_only:
        label += " gesperrt"
    for client in CLIENTS.values():
        if client.train == train:
            return f"{label} ({'Admin' if client.is_admin else client.addr})"
    return label


for train in trains.TRAINS:
    @app.callback([Output(f'admin-lock-{train}', 'style')], [Input(f'admin-lock-{train}', 'value')])
    def admin_lock_train(locked, train=train):
        locked = bool(locked)
        train.admin_only = locked
        if locked:
            train.set_target_speed(0)
        raise PreventUpdate()


def get_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip


def get_incoming(train: trains.Train):
    # if _SCHEDULE_MODE:
    #     return {
    #         'ICE': 'Blue',
    #         'E-Lok (DB)': 'Any',
    #         'E-Lok (BW)': 'Any',
    #         'S-Bahn': 'Yellow',
    #         'Dampf-Lok': 'Yellow',
    #         'Diesel-Lok': 'Yellow',
    #     }[train.name]
    # else:
    return 'Any'


LOCAL_IP = get_ip()
PORT = 8051
SERIAL_PORT: Optional[str] = 'COM4'
RELAY_ERR = None
_SCHEDULE_MODE = False


if __name__ == '__main__':
    try:
        import relay8
        print("Relay initialized, track switches online.")
    except AssertionError as err:
        print(err)
        RELAY_ERR = err
    trains.setup(SERIAL_PORT)
    try:
        import bjoern
        print(f"Starting Bjoern server on {LOCAL_IP}, port {PORT}: http://{LOCAL_IP}:{PORT}/")
        bjoern.run(app.server, port=PORT, host='0.0.0.0')
    except ImportError:
        try:
            import waitress
            print(f"Starting Waitress server on {LOCAL_IP}, port {PORT}: http://{LOCAL_IP}:{PORT}/")
            waitress.serve(app.server, port=PORT)
        except ImportError:
            print(f"Starting debug server on {LOCAL_IP}, port {PORT}: http://{LOCAL_IP}:{PORT}/")
            app.run_server(debug=True, host='0.0.0.0', port=PORT)
    # trains.power_on()
