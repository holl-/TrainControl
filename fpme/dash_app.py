import threading

import dash
import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc
import dash_daq as daq
from dash.dependencies import Input, Output
from dash.exceptions import PreventUpdate

from fpme import drivers, trains


class Client:

    def __init__(self, name):
        self.name = name
        self.accelerations = 0
        self.decelerations = 0
        self.reverses = 0
        self.stops = 0


CLIENTS = {}
INPUT_LOCK = threading.Lock()


CONTROL_UPDATE_INPUTS = [
    Input('name', 'value'),
    Input('accelerate', 'n_clicks'),
    Input('decelerate', 'n_clicks'),
    Input('reverse', 'n_clicks'),
    Input('stop-train', 'n_clicks'),
    Input('main-update', 'n_intervals'),
]


def handle_control_input(name: str, index: int, accelerations: int, decelerations: int, reverses: int, stops: int, _):
    with INPUT_LOCK:
        train, reverse = drivers.get_train(name, index)
        if not train:
            raise PreventUpdate()
        if accelerations is None and decelerations is None and reverses is None and stops is None:
            CLIENTS[name] = Client(name)
        client = CLIENTS[name]

        accelerations = accelerations or 0
        decelerations = decelerations or 0
        reverses = reverses or 0
        stops = stops or 0

        if reverses > client.reverses and train.speed == 0:
            reverse = reverse ^ bool(-1 ** (reverses - client.reverses))
            drivers.set_reverse(name, index, reverse)
        effective_acceleration = accelerations - client.accelerations - (decelerations - client.decelerations)
        train.accelerate(-effective_acceleration if reverse else effective_acceleration, not_backward=not reverse, not_forward=reverse)
        if stops > client.stops:
            train.stop()

        client.accelerations = accelerations
        client.decelerations = decelerations
        client.reverses = reverses
        client.stops = stops


with open('../login_text.md') as file:
    login_text = file.read()

app = dash.Dash('Modelleisenbahn', external_stylesheets=[dbc.themes.BOOTSTRAP])

login_layout = html.Div(id='login', children=[
    dcc.Markdown(login_text),
    html.Div([
        'Name:',
        dcc.Textarea(id='name', value='', rows=1)
    ]),
])

tasks = html.Div(style={}, children=[
        dbc.Row(
            [
                dbc.Col(html.Div("Person")),
                dbc.Col(html.Div("von Grünstein")),
                dbc.Col(html.Div("mit ICE")),
                dbc.Col(html.Div("nach Waldbrunn")),
            ],
        ),
        dbc.Row(
            [
                dbc.Col(html.Div("Güter")),
                dbc.Col(html.Div("von Waldbrunn")),
                dbc.Col(html.Div("-")),
                dbc.Col(html.Div("nach Neuffen")),
            ],
        ),
        dbc.Row(
            [
                dbc.Col(html.Div("Person")),
                dbc.Col(html.Div("von Bav. Film Studios")),
                dbc.Col(html.Div("-")),
                dbc.Col(html.Div("nach Aubing")),
            ],
        ),
    ]
)


def build_control(index):
    return html.Div(style={}, children=[
        html.Div(style={'display': 'inline-block', 'vertical-align': 'top'}, children=[
            daq.Gauge(id='speed', color={'gradient': True, 'ranges': {'green': [0, 6*25], 'yellow': [6*25, 8*25], 'red': [8*25, 10*25]}},
                      value=250, label='Zug - Richtung', max=250, min=0, units='km/h', showCurrentValue=True, size=300),
        ]),
        html.Div(style={'display': 'inline-block', 'width': 80, 'height': 300, 'vertical-align': 'top'}, children=[
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '25%'}, children=[
                html.Button('+', id='accelerate', style={'width': '100%', 'height': '100%', 'background-color': '#33cc33', 'color': 'white'}),
            ]),
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '15%'}, children=[
                html.Button('<->', id='reverse', style={'width': '100%', 'height': '100%', 'background-color': '#A0A0FF', 'color': 'white'}),
            ]),
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '25%'}, children=[
                html.Button('-', id='decelerate', style={'width': '100%', 'height': '100%', 'background-color': '#33cc33', 'color': 'white'}),
            ]),
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '15%'}, children=[
                html.Button('Nothalt', id='stop-train', style={'width': '100%', 'height': '100%', 'background-color': '#ff6600', 'color': 'white'}),
            ]),
            html.Div(style={'display': 'inline-block', 'width': '100%', 'height': '20%'}, children=[
                html.Button('Strom', id='stop-all', style={'width': '100%', 'height': '100%', 'background-color': '#cc0000', 'color': 'white'}),
            ]),
        ]),
    ])


control_layout = html.Div(id='control', style={'display': 'none'}, children=[
    build_control(0),
    tasks,
    html.Div(id='stop-train-placeholder', style={'display': 'none'}),
    html.Div(id='stop-all-placeholder', style={'display': 'none'}),
])


app.layout = html.Div(children=[
    dcc.Interval(id='main-update', interval=1000),
    login_layout,
    control_layout,
])
# app.config.suppress_callback_exceptions = True


@app.callback(Output('login', 'style'), [Input('main-update', 'n_intervals'), Input('name', 'value')])
def hide_login(_n_intervals, name):
    if drivers.get_train(name, 0)[0]:
        return {'display': 'none'}
    raise PreventUpdate()


@app.callback(Output('control', 'style'), [Input('main-update', 'n_intervals'), Input('name', 'value')])
def show_control(_n_intervals, name):
    if drivers.get_train(name, 0)[0]:
        return {}
    raise PreventUpdate()


@app.callback(Output('speed', 'label'), CONTROL_UPDATE_INPUTS)
def set_train_name(name, *args):
    handle_control_input(name, 0, *args)
    train, reverse = drivers.get_train(name, 0)
    return "◀ " + train.name if reverse else train.name + " ▶"  # ⬅➡
    # return train.name + (" - Rückwärts" if reverse else " - Vorwärts")


@app.callback(Output('speed', 'value'), CONTROL_UPDATE_INPUTS)
def update_speedometer(name, *args):
    handle_control_input(name,0,  *args)
    train, _ = drivers.get_train(name, 0)
    return int(round(abs(train.speed) * 250))


@app.callback(Output('stop-all-placeholder', 'children'), [Input('stop-all', 'n_clicks'), Input('name', 'value')])
def power_off(n_clicks, _name):
    if n_clicks is not None:
        trains.stop()
    return str(n_clicks)


if __name__ == '__main__':
    app.run_server(debug=True, host='0.0.0.0', port=8051)
