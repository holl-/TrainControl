import threading

import dash
import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output
from dash.exceptions import PreventUpdate

from fpme import logic


class Client:

    def __init__(self, name):
        self.name = name
        self.accelerations = 0
        self.decelerations = 0


CLIENTS = {}
INPUT_LOCK = threading.Lock()


def client_input(name, accelerations, decelerations):
    with INPUT_LOCK:
        if name not in logic.DRIVERS:
            return
        if accelerations is None and decelerations is None:
            CLIENTS[name] = Client(name)
        accelerations = accelerations or 0
        decelerations = decelerations or 0
        if name in CLIENTS:
            client = CLIENTS[name]
            diff = accelerations - client.accelerations - (decelerations - client.decelerations)
            logic.accelerate(name, diff)
            client.accelerations = accelerations
            client.decelerations = decelerations



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

control_layout = html.Div(id='control', style={'display': 'none'}, children=[
    html.H2('', id='train-name', style={'textAlign': 'center'}),
    html.Div(style={'width': '100%', 'height': 60}, children=[
        html.Button('-', id='decelerate', style={'width': '20%', 'height': '100%', 'display': 'inline-block', 'vertical-align': 'top'}),
        html.Div(style={'width': '60%', 'height': '100%', 'display': 'inline-block', 'vertical-align': 'center'}, children=[
            dbc.Progress('Geschwindigkeit', value=50, color='success', className="mb-3", id='speed', style={'height': '100%'}),
        ]),
        html.Button('+', id='accelerate', style={'width': '20%', 'height': '100%', 'display': 'inline-block', 'vertical-align': 'top'}),
    ]),
    tasks,
    html.Div(style={'width': '50%', 'height': 60, 'margin': 'auto'}, children=[
        html.Button('Nothalt', id='stop-train', style={'width': '40%', 'height': '100%', 'display': 'inline-block', 'vertical-align': 'top', 'horizontal-align': 'left', 'background-color': 'purple', 'color': 'white'}),
        html.Button('Strom aus', id='stop-all', style={'width': '40%', 'height': '100%', 'display': 'inline-block', 'vertical-align': 'top', 'horizontal-align': 'right', 'background-color': 'red', 'color': 'white'}),
    ]),
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
    if logic.can_control(name):
        return {'display': 'none'}
    raise PreventUpdate()


@app.callback(Output('control', 'style'), [Input('main-update', 'n_intervals'), Input('name', 'value')])
def show_control(_n_intervals, name):
    if logic.can_control(name):
        return {}
    raise PreventUpdate()


@app.callback(Output('train-name', 'children'), [Input('main-update', 'n_intervals'), Input('name', 'value')])
def set_train_name(_n_intervals, name):
    if logic.can_control(name):
        return logic.get_train_name(name)
    raise PreventUpdate()


@app.callback(Output('speed', 'value'), [Input('name', 'value'), Input('accelerate', 'n_clicks'), Input('decelerate', 'n_clicks'), Input('stop-train-placeholder', 'children')])
def update_speedometer(name, accelerations, decelerations, *args):
    client_input(name, accelerations, decelerations)
    if logic.can_control(name):
        speed = logic.get_speed(name)
        return int(round(abs(speed) * 100))
    raise PreventUpdate()


@app.callback(Output('speed', 'children'), [Input('name', 'value'), Input('accelerate', 'n_clicks'), Input('decelerate', 'n_clicks')])
def update_speedometer_text(name, accelerations, decelerations):
    client_input(name, accelerations, decelerations)
    if logic.can_control(name):
        speed = logic.get_speed(name)
        return '' if speed >= 0 else 'Rückwärts'
    raise PreventUpdate()


@app.callback(Output('speed', 'color'), [Input('name', 'value'), Input('accelerate', 'n_clicks'), Input('decelerate', 'n_clicks')])
def update_speedometer_color(name, accelerations, decelerations):
    client_input(name, accelerations, decelerations)
    if logic.can_control(name):
        speed = logic.get_speed(name)
        if abs(speed) > 0.95:
            return 'danger'
        if abs(speed) > 0.6:
            return 'warning'
        if speed > 0:
            return 'success'
        if speed < 0:
            return 'info'
    raise PreventUpdate()


@app.callback(Output('stop-train-placeholder', 'children'), [Input('stop-train', 'n_clicks'), Input('name', 'value')])
def stop_train(n_clicks, name):
    if n_clicks is not None:
        logic.stop(name)
    return str(n_clicks)


@app.callback(Output('stop-all-placeholder', 'children'), [Input('stop-all', 'n_clicks'), Input('name', 'value')])
def stop_train(n_clicks, _name):
    if n_clicks is not None:
        logic.stop()
    return str(n_clicks)


if __name__ == '__main__':
    app.run_server(debug=True, host='0.0.0.0', port=1111)

