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

from fpme import trains


class Client:
    PING_TIME = 1.0
    GLOBAL_ID_COUNTER = 0

    def __init__(self, addr):
        self.addr = addr  # IP
        self.user_id = str(Client.GLOBAL_ID_COUNTER)  # generated after website loaded, stored in 'user-id' div component
        Client.GLOBAL_ID_COUNTER += 1
        self.accelerations = 0
        self.decelerations = 0
        self.reverses = 0
        self.stops = 0
        self.train = None
        self.last_input_perf_counter = time.perf_counter()
        self.train_clicks = [0] * len(trains.TRAINS)

    def __repr__(self):
        return f"{self.user_id} @ {self.addr} controlling {self.train}"

    def is_inactive(self):
        return time.perf_counter() - self.last_input_perf_counter > Client.PING_TIME * 4


CLIENTS: Dict[str, Client] = {}  # id -> Client


def clear_inactive_clients():
    for client in tuple(CLIENTS.values()):
        if client.is_inactive():
            del CLIENTS[client.user_id]
            if client.train is not None:
                client.train.stop()

# INPUT_LOCK = threading.Lock()

app = dash.Dash('Modelleisenbahn', external_stylesheets=[dbc.themes.BOOTSTRAP])

with open('../welcome_text.md') as file:
    welcome_text = file.read()
welcome_layout = html.Div(id='welcome', children=[
    dcc.Markdown(welcome_text),
])

# tasks = html.Div(style={}, children=[
#         dbc.Row(
#             [
#                 dbc.Col(html.Div("Person")),
#                 dbc.Col(html.Div("von Grünstein")),
#                 dbc.Col(html.Div("mit ICE")),
#                 dbc.Col(html.Div("nach Waldbrunn")),
#             ],
#         ),
#         dbc.Row(
#             [
#                 dbc.Col(html.Div("Güter")),
#                 dbc.Col(html.Div("von Waldbrunn")),
#                 dbc.Col(html.Div("-")),
#                 dbc.Col(html.Div("nach Neuffen")),
#             ],
#         ),
#         dbc.Row(
#             [
#                 dbc.Col(html.Div("Person")),
#                 dbc.Col(html.Div("von Bav. Film Studios")),
#                 dbc.Col(html.Div("-")),
#                 dbc.Col(html.Div("nach Aubing")),
#             ],
#         ),
#     ]
# )


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
            daq.Gauge(id='speed', color={'gradient': True, 'ranges': {'green': [0, 6*25], 'yellow': [6*25, 8*25], 'red': [8*25, 10*25]}},
                      value=250, label='Zug - Richtung', max=250, min=0, units='km/h', showCurrentValue=True, size=300),
        ]),
        html.Div([], style={'display': 'inline-block', 'width': 40, 'height': 300, 'vertical-align': 'bottom'}),
        html.Div(style={'display': 'inline-block', 'width': 120, 'height': 300, 'vertical-align': 'top'}, children=[
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '30%'}, children=[
                html.Button('+', id='accelerate', style={'width': '100%', 'height': '100%', 'background-color': '#33cc33', 'color': 'white'}),
            ]),
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '20%'}, children=[
                html.Button('<->', id='reverse', style={'width': '100%', 'height': '100%', 'background-color': '#A0A0FF', 'color': 'white'}),
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
    *[html.Button(train.name, id=f'switch-to-{train.name}') for train in trains.TRAINS],
    html.Div([], style={'display': 'inline-block', 'width': 10, 'height': 10}),
    html.Button("Aussteigen", id='release-train')
])
# disable button when train in use
TRAIN_BUTTONS = [Input(f'switch-to-{train.name}', 'n_clicks') for train in trains.TRAINS]


control_layout = html.Div(id='control', style={'display': 'none'}, children=[
    build_control(0),
    html.Div(id='stop-train-placeholder', style={'display': 'none'}),
])


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


app.layout = html.Div(children=[
    dcc.Location(id='url', refresh=False),
    dcc.Interval(id='main-update', interval=Client.PING_TIME * 1000),
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
        client = Client(request.remote_addr)
        CLIENTS[client.user_id] = client
        print(f"Registered client {client} (loaded {url})")
        return client.user_id
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
    client = CLIENTS[user_id]
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
                    client.train = train
        client.train_clicks = [new if new is not None else old for new, old in zip(n_clicks, client.train_clicks)]
        return [({} if client.train is not None else {'display': 'none'}), label, *blocked_trains, release_disabled]
    else:
        raise PreventUpdate()


@app.callback(Output('release-train', 'style'), [Input('user-id', 'children'), Input('release-train', 'n_clicks')])
def release_train(user_id, n_clicks):
    if n_clicks is not None and n_clicks > 0:
        CLIENTS[user_id].train = None
    raise PreventUpdate()


@app.callback(Output('speed', 'value'),
              [Input('user-id', 'children'), Input('accelerate', 'n_clicks'), Input('decelerate', 'n_clicks'), Input('reverse', 'n_clicks'), Input('stop-train', 'n_clicks'), Input('main-update', 'n_intervals')])
def train_control_and_speedometer_update(user_id, accelerations, decelerations, reverses, stops, _n):
    client = CLIENTS[user_id]
    if client.train is None:
        raise PreventUpdate()

    accelerations, decelerations, reverses, stops = [x or 0 for x in [accelerations, decelerations, reverses, stops]]

    if reverses > client.reverses and client.train.is_parked:
        if -1 ** (reverses - client.reverses):
            client.train.reverse()
    effective_acceleration = accelerations - client.accelerations - (decelerations - client.decelerations)
    if effective_acceleration != 0:
        client.train.accelerate_snap(effective_acceleration)
    if stops > client.stops:
        client.train.stop()

    client.accelerations, client.decelerations, client.reverses, client.stops = accelerations, decelerations, reverses, stops
    return int(round(client.train.abs_speed / 14 * 250))


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
        train.set_signed_speed(value)
        raise PreventUpdate()


@app.callback([Output(f'admin-speedometer-{train.name}', 'value') for train in trains.TRAINS], [Input('main-update', 'n_intervals')])
def display_admin_speeds(_n):
    return [0.5 * (1 + train.signed_speed / 14) for train in trains.TRAINS]


if __name__ == '__main__':
    # trains.power_on()
    app.run_server(debug=True, host='0.0.0.0', port=8051)  # TODO port 80
