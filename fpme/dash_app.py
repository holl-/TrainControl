import math
import random
import threading
import time
from typing import Dict

from flask import request
import dash
import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc
import dash_daq as daq
from dash.dependencies import Input, Output
from dash.exceptions import PreventUpdate

from fpme import trains, switches


class Client:
    PING_TIME = 1.0
    GLOBAL_ID_COUNTER = 0
    APP_INSTANCE_ID = int(time.time())

    def __init__(self, addr, user_id=None):
        self.addr = addr  # IP
        if user_id is None:
            self.user_id = f'{Client.APP_INSTANCE_ID}-{Client.GLOBAL_ID_COUNTER}'  # generated after website loaded, stored in 'user-id' div component
            Client.GLOBAL_ID_COUNTER += 1
        else:
            self.user_id = user_id
        self.accelerations = 0
        self.decelerations = 0
        self.reverses = 0
        self.stops = 0
        self.switches = 0
        self.train = None
        self.last_input_perf_counter = time.perf_counter()
        self.train_clicks = [0] * len(trains.TRAINS)

    def __repr__(self):
        return f"{self.user_id} @ {self.addr} controlling {self.train}"

    def is_inactive(self):
        return time.perf_counter() - self.last_input_perf_counter > Client.PING_TIME * 4


CLIENTS: Dict[str, Client] = {}  # id -> Client


def get_client(user_id: str or None) -> Client:
    """
    Args:
        user_id: if `str`, looks up or creates a client with the given ID, if `None`, generates a new ID.
    """
    if user_id in CLIENTS:
        return CLIENTS[user_id]
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

# INPUT_LOCK = threading.Lock()

app = dash.Dash('Modelleisenbahn', external_stylesheets=[dbc.themes.BOOTSTRAP, 'radio-buttons.css'])

with open('../welcome_text.md') as file:
    welcome_text = file.read()
welcome_layout = html.Div(id='welcome', children=[
    dcc.Markdown(welcome_text),
])


def build_control(index):
    return html.Div(style={}, children=[
        html.Div(style={'display': 'inline-block', 'width': 120, 'height': 300, 'vertical-align': 'center'}, children=[
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '40%'}, children=[
                html.Button('Strom an', id='power-on', style={'width': '100%', 'height': '100%'}, disabled=True),
            ]),
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '60%'}, children=[
                html.Button('Strom aus', id='power-off', style={'width': '100%', 'height': '100%', 'background-color': '#cc0000', 'color': 'white'}),
            ]),
        ]),
        html.Div([], style={'display': 'inline-block', 'width': 40, 'height': 300, 'vertical-align': 'bottom'}),
        html.Div(style={'display': 'inline-block', 'vertical-align': 'top'}, children=[
            daq.Gauge(id='speed', value=0, label='Zug - Richtung', max=250, min=0, units='km/h', showCurrentValue=True, size=300),
        ]),
        html.Div([], style={'display': 'inline-block', 'width': 40, 'height': 300, 'vertical-align': 'bottom'}),
        html.Div(style={'display': 'inline-block', 'width': 120, 'height': 300, 'vertical-align': 'top'}, children=[
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '30%'}, children=[
                html.Button('+', id='accelerate', style={'width': '100%', 'height': '100%', 'background-color': '#33cc33', 'color': 'white'}),
            ]),
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '20%'}, children=[
                html.Button('◄ ►', id='reverse', style={'width': '100%', 'height': '100%', 'background-color': '#A0A0FF', 'color': 'white'}),
            ]),
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '30%'}, children=[
                html.Button('-', id='decelerate', style={'width': '100%', 'height': '100%', 'background-color': '#33cc33', 'color': 'white'}),
            ]),
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '20%'}, children=[
                html.Button('Nothalt', id='stop-train', style={'width': '100%', 'height': '100%', 'background-color': '#dd5500', 'color': 'white'}),
            ]),
        ]),
    ])


switch_trains = html.Div([
    *[html.Button(train.name, id=f'switch-to-{train.name}', disabled=True) for train in trains.TRAINS],
    html.Div([], style={'display': 'inline-block', 'width': 10, 'height': 10}),
    html.Button("Aussteigen", id='release-train')
])
# disable button when train in use
TRAIN_BUTTONS = [Input(f'switch-to-{train.name}', 'n_clicks') for train in trains.TRAINS]


admin_controls = []
for train in trains.TRAINS:
    admin_controls.append(html.Div([
        train.name,
        dcc.Slider(id=f'admin-slider-{train.name}', min=-14, max=14, value=0, marks={0: '0', 14: 'Vorwärts', -14: 'Rückwärts'}),
        dbc.Progress(id=f'admin-speedometer-{train.name}', value=0.5, max=1),
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
    dcc.Checklist(id='admin-checklist', options=[{'label': "Weichen Sperren", 'value': 'lock-all-switches'}], value=[])
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
    build_control(0),
    html.Div(id='stop-train-placeholder', style={'display': 'none'}),
    track_switch_controls,
])


app.layout = html.Div(children=[
    dcc.Location(id='url', refresh=False),
    dcc.Interval(id='main-update', interval=Client.PING_TIME * 1000),
    dcc.Interval(id='speed-update', interval=200),
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
               Output('release-train', 'disabled')],
              [Input('user-id', 'children'), Input('main-update', 'n_intervals'), *TRAIN_BUTTONS])
def main_update(user_id, _n_intervals, *n_clicks):
    client = get_client(user_id)
    client.last_input_perf_counter = time.perf_counter()
    clear_inactive_clients()

    if client.train is None:
        label = " "
    else:
        label = "◀ " + client.train.name if client.train.in_reverse else client.train.name + " ▶"  # ⬅➡
    if not trains.is_power_on():
        label += " (Kein Strom)"

    if client.train is not None and not client.train.is_parked:
        blocked_trains = [True] * len(trains.TRAINS)
        release_disabled = True
    else:
        blocked_trains = [any([client.train == train for client in CLIENTS.values()]) for train in trains.TRAINS]
        release_disabled = False

    if n_clicks is not None:
        for train, prev_clicks, bt_n_clicks in zip(trains.TRAINS, client.train_clicks, n_clicks):
            if bt_n_clicks is not None and bt_n_clicks > prev_clicks:
                if all([c.train != train for c in CLIENTS.values()]):  # train not in use
                    if client.train is not None:
                        client.train.set_target_speed(0)
                    client.train = train
        client.train_clicks = [new if new is not None else old for new, old in zip(n_clicks, client.train_clicks)]
        return [({} if client.train is not None else {'display': 'none'}), label, *blocked_trains, release_disabled]
    else:
        raise PreventUpdate()


@app.callback(Output('release-train', 'style'), [Input('user-id', 'children'), Input('release-train', 'n_clicks')])
def release_train(user_id, n_clicks):
    if n_clicks is not None and n_clicks > 0:
        client = get_client(user_id)
        if client.train is not None:
            client.train.set_target_speed(0)
            client.train = None
    raise PreventUpdate()


@app.callback([Output('speed', 'value'), Output('speed', 'max'), Output('speed', 'color')],
              [Input('user-id', 'children'), Input('accelerate', 'n_clicks'), Input('decelerate', 'n_clicks'), Input('reverse', 'n_clicks'), Input('stop-train', 'n_clicks'), Input('speed-update', 'n_intervals')])
def train_control_and_speedometer_update(user_id, accelerations, decelerations, reverses, stops, _n):
    client = get_client(user_id)
    if client.train is None:
        raise PreventUpdate()

    accelerations, decelerations, reverses, stops = [x or 0 for x in [accelerations, decelerations, reverses, stops]]

    if reverses > client.reverses and client.train.is_parked:
        if -1 ** (reverses - client.reverses):
            client.train.reverse()
    effective_acceleration = accelerations - client.accelerations - (decelerations - client.decelerations)
    if effective_acceleration != 0:
        client.train.accelerate(effective_acceleration)
    if stops > client.stops:
        client.train.emergency_stop()

    client.accelerations, client.decelerations, client.reverses, client.stops = accelerations, decelerations, reverses, stops
    speed = int(round(abs(client.train.signed_actual_speed)))
    max_speed = int(round(client.train.max_speed))
    if speed > 10:
        speed += int(round(0.4 * math.sin(time.time()) + 0.7 * math.sin(time.time() * 1.3) + 0.3 * math.sin(time.time() * 0.7) + random.random() * 0.2))
    color = {'gradient': True, 'ranges': {'green': [0, .6 * max_speed], 'yellow': [.6 * max_speed, .8 * max_speed], 'red': [.8 * max_speed, max_speed]}}
    if not trains.is_power_on():
        speed = 0
        color = 'blue'
    return speed, max_speed, color


@app.callback(Output('power-off', 'style'), [Input('power-off', 'n_clicks')])
def power_off(n_clicks):
    if n_clicks is not None:
        trains.power_off()
    raise PreventUpdate()


@app.callback(Output('power-off-admin', 'style'), [Input('power-off-admin', 'n_clicks')])
def power_off_admin(n_clicks):
    if n_clicks is not None:
        trains.power_off()
    raise PreventUpdate()


@app.callback(Output('power-on', 'style'), [Input('power-on', 'n_clicks')])
def power_on(n_clicks):
    if time.perf_counter() - trains.POWER_OFF_TIME > 5:
        if n_clicks is not None:
            trains.power_on()
    raise PreventUpdate()


@app.callback(Output('power-on', 'disabled'), [Input('main-update', 'n_intervals')])
def enable_power_on(_n):
    return time.perf_counter() - trains.POWER_OFF_TIME < 5 or trains.is_power_on()


@app.callback(Output('power-on-admin', 'style'), [Input('power-on-admin', 'n_clicks')])
def power_on_admin(n_clicks):
    if n_clicks is not None:
        trains.power_on()
    raise PreventUpdate()


@app.callback(Output('admin-controls', 'children'), [Input('url', 'pathname')])
def show_admin_controls(path):
    return admin_controls if path == '/admin' else []


for train in trains.TRAINS:
    @app.callback(Output(f'admin-speedometer-{train.name}', 'style'), [Input(f'admin-slider-{train.name}', 'value')])
    def set_speed_admin(value, train=train):
        train.set_target_speed(value / 14 * train.max_speed)
        raise PreventUpdate()


@app.callback([Output(f'admin-speedometer-{train.name}', 'value') for train in trains.TRAINS], [Input('main-update', 'n_intervals')])
def display_admin_speeds(_n):
    return [0.5 * (1 + train.signed_actual_speed / train.max_speed) for train in trains.TRAINS]


@app.callback([Output('admin-checklist', 'style')], [Input('admin-checklist', 'value')])
def admin_checklist_update(selection):
    lock = 'lock-all-switches' in selection
    switches.set_all_locked(lock)
    raise PreventUpdate


@app.callback([Output('switch-tracks-status', 'children'), Output('switch-tracks-button', 'disabled')],
              [Input('user-id', 'children'), Input('main-update', 'n_intervals'),
               Input('switch-track', 'value'), Input('switch-platform', 'value'), Input('switch-is_arrival', 'value'), Input('switch-tracks-button', 'n_clicks')])
def is_switch_impossible(user_id, _n, track: str, platform: int, is_arrival: bool, n_clicks: int):
    client = get_client(user_id)

    locked: float = switches.check_lock(is_arrival, platform, track)

    if n_clicks is not None and n_clicks > client.switches:  # Set switches
        client.switches = n_clicks
        if not locked:
            switches.set_switches(arrival=is_arrival, platform=platform, track=track)

    if is_arrival:
        possible = switches.get_possible_arrival_platforms(track)
        setting_possible = platform in possible
    else:
        possible = switches.get_possible_departure_tracks(platform)
        setting_possible = track in possible
    if setting_possible:
        correct = switches.are_switches_correct_for(is_arrival, platform, track)
        if correct or len(possible) == 1:
            status = "Korrekt gestellt"
        elif locked == float('inf'):
            status = "Weichen momentan gesperrt."
        elif locked:
            status = f"Warte auf anderen Zug ({int(locked)+1} s)"
        else:
            status = ""
    else:
        correct = False
        status = f"Nur {', '.join(str(p) for p in possible)} möglich." if len(possible) > 1 else f"Fährt immer auf {possible[0]}"
    return status, not setting_possible or correct or locked


def get_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip


def start_app(serial_port: str = None,
              port: int = 80):
    try:
        import relay8
        print("Relay initialized, track switches online.")
    except AssertionError as err:
        print(err)
    trains.setup(serial_port)
    # trains.power_on()
    import waitress
    print(f"Starting server on {get_ip()}:{port}")
    waitress.serve(app.server, port=port)
    # app.run_server(debug=True, host='0.0.0.0', port=port)


if __name__ == '__main__':
    start_app()
