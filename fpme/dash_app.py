import time
from typing import Dict

from flask import request
import dash
import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc
import dash_daq as daq
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate
from dash import callback_context

from fpme import trains, switches


class Client:
    PING_TIME = 2.0  # Max time between main updates
    GLOBAL_ID_COUNTER = 0
    APP_INSTANCE_ID = int(time.time())

    def __init__(self, addr, user_id=None):
        self.addr = addr  # IP
        if user_id is None:
            self.user_id = f'{Client.APP_INSTANCE_ID}-{Client.GLOBAL_ID_COUNTER}'  # generated after website loaded, stored in 'user-id' div component
            Client.GLOBAL_ID_COUNTER += 1
        else:
            self.user_id = user_id
        self.train = None
        self.last_input_perf_counter = time.perf_counter()

    def __repr__(self):
        return f"{self.user_id} @ {self.addr} controlling {self.train}"

    def is_inactive(self):
        return time.perf_counter() - self.last_input_perf_counter > Client.PING_TIME * 2.5


CLIENTS: Dict[str, Client] = {}  # id -> Client


def get_client(user_id: str or None, register_heartbeat=True) -> Client:
    """
    Args:
        user_id: if `str`, looks up or creates a client with the given ID, if `None`, generates a new ID.
    """
    if user_id in CLIENTS:
        client = CLIENTS[user_id]
        if register_heartbeat:
            client.last_input_perf_counter = time.perf_counter()
        return client
    else:
        client = Client(request.remote_addr, user_id)
        print(f"Registered client {client}")
        CLIENTS[client.user_id] = client
        return client


def clear_inactive_clients():
    for client in tuple(CLIENTS.values()):
        if client.is_inactive():
            del CLIENTS[client.user_id]
            if client.train is not None:
                client.train.set_target_speed(0)


app = dash.Dash('Modelleisenbahn', external_stylesheets=[dbc.themes.BOOTSTRAP, 'radio-buttons.css'])

with open('../welcome_text.md') as file:
    welcome_text = file.read()
welcome_layout = html.Div(id='welcome', children=[
    dcc.Markdown(welcome_text),
])


def build_control():
    return html.Div(style={}, children=[
        html.Div(style={'display': 'inline-block', 'width': 120, 'height': 300, 'vertical-align': 'top'}, children=[
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '40%'}, children=[
                html.Button('⌁', id='power-on', style={'width': '100%', 'height': '100%', 'font-size': '66px'}, disabled=True),  # ⌁⚡
            ]),
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '60%'}, children=[
                html.Button('⚠', id='power-off', style={'width': '100%', 'height': '100%', 'font-size': '66px', 'background-color': '#cc0000', 'color': 'white'}),
            ]),
        ]),
        html.Div([], style={'display': 'inline-block', 'width': 40, 'height': 300, 'vertical-align': 'bottom'}),
        html.Div(style={'display': 'inline-block', 'vertical-align': 'top'}, children=[
            daq.Gauge(id='speed', value=0, label='Zug - Richtung', max=250, min=0, units='km/h', showCurrentValue=False, size=300),
        ]),
        html.Div(style={'display': 'inline-block', 'width': 60, 'height': 300, 'vertical-align': 'center'}, children=[
            dcc.Slider(id='speed-control', min=0, max=10, step=None, value=0, marks={0: '', 100: '', 200: ''}, updatemode='drag', vertical=True, verticalHeight=320),
        ]),
        html.Div(style={'display': 'inline-block', 'width': 120, 'height': 300}, children=[
            html.Div(style={'display': 'inline-block', 'width': 120, 'height': 60}, children=[
                html.Button('+', id='accelerate1', style={'width': '100%', 'height': '100%', 'background-color': '#499936', 'color': 'white'}),
            ]),
            html.Div(style={'display': 'inline-block', 'width': 120, 'height': 40}, children=[
                html.Button('◄ ►', id='reverse', style={'width': '100%', 'height': '100%'}),  # , 'background-color': '#A0A0FF', 'color': 'white'
            ]),
            html.Div(style={'display': 'inline-block', 'width': 120, 'height': 60}, children=[
                html.Button('-', id='decelerate1', style={'width': '100%', 'height': '100%', 'background-color': '#499936', 'color': 'white'}),
            ]),
            html.Div(style={'display': 'inline-block', 'width': 120, 'height': 40}, children=[]),
            html.Div(style={'display': 'inline-block', 'width': 120, 'height': 80}, children=[
                html.Button('🛑', id='stop-train', style={'width': '100%', 'height': '100%', 'font-size': '48px', 'background-color': '#FF8000', 'color': 'white'}),  # ⛔
            ]),
            html.Div(style={'display': 'inline-block', 'width': 120, 'height': 10}, children=[]),
        ]),
        dcc.Store('target-speed-store'),
        dcc.Store('acceleration-store'),
        dcc.Store('needle-velocity'),
    ])


TRAIN_LABELS = {  # 🚄 🚅 🚂 🛲 🚉 🚆 🚋 🚇
    'ICE': "🚅 ICE",
    'E-Lok (DB)': "🚉 DB",
    'E-Lok (BW)': "🚉 BW",
    'S-Bahn': "Ⓢ Bahn",
    'Dampf-Lok': "🚂 Dampf",
    'Diesel-Lok': "🛲 Diesel",
}
switch_trains = html.Div([
    html.Div([], style={'display': 'inline-block', 'width': 70, 'height': 10}),
    *[html.Button(TRAIN_LABELS[train.name], id=f'switch-to-{train.name}', disabled=True) for train in trains.TRAINS],
    html.Div([], style={'display': 'inline-block', 'width': 10, 'height': 10}),
    html.Button("🚪⬏", id='release-train', disabled=True)  # Aussteigen
])
# disable button when train in use
TRAIN_BUTTONS = [Input(f'switch-to-{train.name}', 'n_clicks') for train in trains.TRAINS]


admin_controls = []
for train in trains.TRAINS:
    admin_controls.append(html.Div(style={'width': '80%'}, children=[
        html.Div(style={'display': 'inline-block', 'width': 200}, children=[
            dbc.Progress(id=f'admin-speedometer-{train.name}', value=0.5, max=1),
        ]),
        train.name,
    ]))
admin_controls.append(html.Div(style={'height': 60}, children=[
    html.Div(style={'display': 'inline-block', 'width': '50%', 'height': '100%'}, children=[
        html.Button('Strom an', id='power-on-admin', style={'width': '100%', 'height': '100%'}),
    ]),
    html.Div(style={'display': 'inline-block', 'width': '50%', 'height': '100%'}, children=[
        html.Button('Strom aus', id='power-off-admin', style={'width': '100%', 'height': '100%', 'background-color': '#cc0000', 'color': 'white'}),
    ]),
]))
admin_controls.append(html.Div(children=[
    dcc.Checklist(id='admin-checklist', options=[
        {'label': "Weichen Sperren", 'value': 'lock-all-switches'},
        {'label': "Geschwindigkeitsbeschränkung auf 150 km/h", 'value': 'global-speed-limit'},
    ], value=[])
]))


track_switch_controls = html.Div(className="radio-group", children=[
    "Weichen: ",
    dbc.RadioItems(
        id="switch-track",
        className="btn-group",
        labelClassName="btn btn-secondary",
        labelCheckedClassName="active",
        options=[
            {"label": "A", "value": 'A'},
            {"label": "B", "value": 'B'},
            {"label": "C", "value": 'C'},
            {"label": "D", "value": 'D'},
        ],
        value='A',
        labelStyle={'display': 'block'}),
    " ",
    dbc.RadioItems(
        id="switch-is_arrival",
        className="btn-group",
        labelClassName="btn btn-secondary",
        labelCheckedClassName="active",
        options=[
            {"label": "🡸", "value": False},
            {"label": "🡺", "value": True},
        ],
        value=True,
        labelStyle={'display': 'block'}),
    " ",
    dbc.RadioItems(
        id="switch-platform",
        className="btn-group",
        labelClassName="btn btn-secondary",
        labelCheckedClassName="active",
        options=[
            {"label": "1", "value": 1},
            {"label": "2", "value": 2},
            {"label": "3", "value": 3},
        ],
        value=1,
        labelStyle={'display': 'block'}),
    " ",
    html.Div(id='switch-tracks-status', style={'display': 'inline-block'}),
    " ",
    html.Button('Stellen', id='switch-tracks-button')
])


control_layout = html.Div(id='control', style={'display': 'none'}, children=[
    build_control(),
    html.Div(id='stop-train-placeholder', style={'display': 'none'}),
    # track_switch_controls,
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


@app.callback(Output('user-id', 'children'), [Input('url', 'pathname')])
def generate_id(url):
    if url:
        return get_client(None).user_id
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
               Output('acceleration-store', 'data')],
              [Input('user-id', 'children'), Input('main-update', 'n_intervals'),
               Input('power-off', 'n_clicks'), Input('power-on', 'n_clicks'),
               Input('reverse', 'n_clicks'),
               Input('release-train', 'n_clicks'), *TRAIN_BUTTONS])
def main_update(user_id, *args):
    trigger = callback_context.triggered[0]
    trigger_id, trigger_prop = trigger["prop_id"].split(".")
    client = get_client(user_id)
    clear_inactive_clients()

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
    if trigger_id == 'reverse':
        if client.train:
            client.train.reverse()

    # Gather info to display
    if client.train is None:
        label = " "
    else:
        train_name = TRAIN_LABELS[client.train.name]
        label = "◀ " + train_name if client.train.in_reverse else train_name + " ▶"  # ⬅➡
    if not trains.is_power_on():
        label += " ⚡"  # Kein Strom  ⚡⌁

    if client.train is not None and not client.train.is_parked:
        blocked_trains = [True] * len(trains.TRAINS)
        release_disabled = True
    else:
        blocked_trains = [any([client.train == train for client in CLIENTS.values()]) for train in trains.TRAINS]
        release_disabled = client.train is None

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
    ]


app.clientside_callback(
    """
    function(n, speed, last_acceleration, target, target_acceleration, dt) {
        if(Number(target) === target) {  // Real update
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
                eff_acceleration *= Math.pow(Math.abs(speed - target) / 30 * 20 / target_acceleration, dt / 1000)
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
    [State('speed', 'value'), State('needle-velocity', 'data'), State('target-speed-store', 'data'), State('acceleration-store', 'data'), State('client-interval', 'interval')]
)


@app.callback([Output('target-speed-store', 'data'), Output('reverse', 'disabled')],
              [Input('speed-control', 'value'), Input('power-status-store', 'data')],  # power-status-store is updated regularly
              [State('user-id', 'children')])
def speed_update(target_speed, _power, user_id):
    client = get_client(user_id)
    trigger = callback_context.triggered[0]
    trigger_id, trigger_prop = trigger["prop_id"].split(".")
    if trigger_id == 'speed-control':
        if client.train:
            client.train.set_target_speed(-target_speed if client.train.in_reverse else target_speed)
    if client.train and client.train.is_emergency_stopping:
        return -1, False
    if client.train:
        return abs(client.train.target_speed) if trains.is_power_on() else -1, client.train.target_speed != 0
    else:
        return -1, True


@app.callback(Output('speed-control', 'value'),
              [Input('accelerate1', 'n_clicks'), Input('decelerate1', 'n_clicks'), Input('stop-train', 'n_clicks')],
              [State('user-id', 'children')])
def speed_update(*args):
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

@app.callback(Output('power-off-admin', 'style'), [Input('power-off-admin', 'n_clicks')])
def power_off_admin(n_clicks):
    if n_clicks is not None:
        trains.power_off()
    raise PreventUpdate()


@app.callback(Output('power-on-admin', 'style'), [Input('power-on-admin', 'n_clicks')])
def power_on_admin(n_clicks):
    if n_clicks is not None:
        trains.power_on()
    raise PreventUpdate()


@app.callback(Output('admin-controls', 'children'), [Input('url', 'pathname')])
def show_admin_controls(path):
    return admin_controls if path == '/admin' else []


@app.callback([Output(f'admin-speedometer-{train.name}', 'value') for train in trains.TRAINS], [Input('main-update', 'n_intervals')])
def display_admin_speeds(_n):
    return [abs(train.target_speed) / train.max_speed for train in trains.TRAINS]


@app.callback([Output('admin-checklist', 'style')], [Input('admin-checklist', 'value')])
def admin_checklist_update(selection):
    switches.set_all_locked('lock-all-switches' in selection)
    trains.set_global_speed_limit(150 if 'global-speed-limit' in selection else None)
    raise PreventUpdate


# @app.callback([Output('switch-tracks-status', 'children'), Output('switch-tracks-button', 'disabled')],
#               [Input('user-id', 'children'), Input('main-update', 'n_intervals'),
#                Input('switch-track', 'value'), Input('switch-platform', 'value'), Input('switch-is_arrival', 'value'), Input('switch-tracks-button', 'n_clicks')])
# def is_switch_impossible(user_id, _n, track: str, platform: int, is_arrival: bool, n_clicks: int):
#     print(f"switch update for {user_id}")
#
#     client = get_client(user_id)
#
#     locked: float = switches.check_lock(is_arrival, platform, track)
#
#     if n_clicks is not None and n_clicks > client.n_switches:  # Set switches
#         client.n_switches = n_clicks
#         if not locked:
#             switches.set_switches(arrival=is_arrival, platform=platform, track=track)
#
#     if is_arrival:
#         possible = switches.get_possible_arrival_platforms(track)
#         setting_possible = platform in possible
#     else:
#         possible = switches.get_possible_departure_tracks(platform)
#         setting_possible = track in possible
#     if setting_possible:
#         correct = switches.are_switches_correct_for(is_arrival, platform, track)
#         if correct or len(possible) == 1:
#             status = "Korrekt gestellt"
#         elif locked == float('inf'):
#             status = "Weichen momentan gesperrt."
#         elif locked:
#             status = f"Warte auf anderen Zug ({int(locked)+1} s)"
#         else:
#             status = ""
#     else:
#         correct = False
#         status = f"Nur {', '.join(str(p) for p in possible)} möglich." if len(possible) > 1 else f"Fährt immer auf {possible[0]}"
#     return status, not setting_possible or correct or locked


def get_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip


def start_app(serial_port: str = None,
              port: int = 8051):
    try:
        import relay8
        print("Relay initialized, track switches online.")
    except AssertionError as err:
        print(err)
    trains.setup(serial_port)
    ip = get_ip()
    try:
        import bjoern
        print(f"Starting Bjoern server on {ip}, port {port}: http://{ip}:{port}/")
        bjoern.run(app.server, port=port, host='0.0.0.0')
    except ImportError:
        try:
            import waitress
            print(f"Starting Waitress server on {ip}, port {port}: http://{ip}:{port}/")
            waitress.serve(app.server, port=port)
        except ImportError:
            print(f"Starting debug server on {ip}, port {port}: http://{ip}:{port}/")
            app.run_server(debug=True, host='0.0.0.0', port=port)
    # trains.power_on()


if __name__ == '__main__':
    start_app()
