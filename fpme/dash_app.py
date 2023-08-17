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

from . import train_control, switches, signal_gen, train_def


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


def fit_image_size(img_res, max_width, max_height):
    image_aspect = img_res[0] / img_res[1]
    max_aspect = max_width / max_height
    if image_aspect > max_aspect:  # wide image: fit width
        return max_width, img_res[1] * max_width / img_res[0]
    else:  # narrow image: fit height
        return img_res[0] * max_height / img_res[1], max_height


class Server:

    def __init__(self, control: train_control.TrainControl):
        self.control = control
        self.app = app = dash.Dash('Modelleisenbahn', external_stylesheets=[dbc.themes.BOOTSTRAP, 'slider.css'], title='Modelleisenbahn', update_title=None)
        self.port = None

        with open('welcome_text.md') as file:
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
            *[html.Button([html.Img(src=f'assets/{train.img_path}', style={d: s for d, s in zip(['width', 'height'], fit_image_size(train.img_res, 60, 20))}), train.name], id=f'switch-to-{train.name}', disabled=True) for train in control.trains],
            html.Div([], style={'display': 'inline-block', 'width': 10, 'height': 10}),
            html.Button("🚪⬏", id='release-train', disabled=False)  # Aussteigen
        ])
        # disable button when train in use
        TRAIN_BUTTONS = [Input(f'switch-to-{train.name}', 'n_clicks') for train in control.trains]


        admin_controls = [
            html.Button("Beenden", id='admin-kill'),
            dcc.Markdown("# Status", id='admin-status'),
            dcc.Checklist(id='admin-checklist', labelStyle=dict(display='block'), options=[
                {'label': "Max 100 km/h", 'value': 'global-speed-limit'},
                {'label': "Weichen sperren", 'value': 'lock-all-switches'},
                {'label': "Lichter an", 'value': 'lights-on'},
            ]),
        ]
        for train in control.trains:
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
                       *[Output(f'switch-to-{train.name}', 'disabled') for train in control.trains],
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
            self.clear_inactive_clients()
            is_admin = client.is_admin

            if client.train is not None and control.is_locked(client.train) and not is_admin:
                client.train = None

            # Button actions
            if trigger_id == 'power-off':
                control.power_off(client.train)
            elif trigger_id == 'power-on':
                control.power_on(client.train)
                time.sleep(0.2)
            elif trigger_id.startswith('switch-to-'):
                if client.train is None or control.is_parked(client.train):
                    new_train_name = trigger_id[len('switch-to-'):]
                    new_train = train_def.TRAINS_BY_NAME[new_train_name]
                    if all([c.train != new_train for c in CLIENTS.values()]):  # train not in use
                        if client.train is not None:
                            control.set_target_speed(client.train, 0)  # Stop the train we're exiting
                        client.train = new_train
            elif trigger_id == 'release-train' and client.train is not None:
                if client.train:
                    control.set_target_speed(client.train, 0)
                    client.train = None
            elif trigger_id == 'reverse':
                if client.train:
                    control.reverse(client.train)
            elif trigger_id.startswith('set-switches-'):
                raise NotImplementedError
                # track = trigger_id[len('set-switches-'):]
                # if client.train:
                #     if switches.can_set(incoming=get_incoming(client.train), track=track, ignore_lock=is_admin):
                #         switches.set_switches(incoming=get_incoming(client.train), track=track)

            # Gather info to display
            if client.train is None:
                label = " "
            else:
                # train_name = f"{client.train.name}"  # {client.train.icon}
                label = client.train.name  # "◀ " + train_name if client.train.in_reverse else train_name + " ▶"
            if not control.is_power_on(client.train):
                label += " ⚡"  # Kein Strom  ⚡⌁

            if client.train is not None and not control.is_parked(client.train) and not is_admin:
                blocked_trains = [True] * len(control.trains)
            else:
                blocked_trains = [(control.is_locked(train) and not is_admin) or any([client.train == train for client in CLIENTS.values()]) for train in control.trains]

            power_on_disabled = False  # time.perf_counter() - control.POWER_OFF_TIME < 5 or control.is_power_on()

            max_speed = int(round(client.train.max_speed)) if client.train else 1
            # color = {'gradient': True, 'ranges': {'green': [0, .6 * max_speed], 'yellow': [.6 * max_speed, .8 * max_speed], 'red': [.8 * max_speed, max_speed]}} if trains.is_power_on() else 'blue'
            color = 'green' if control.is_power_on(client.train) else 'blue'
            if client.train:
                marks = {speed: '' for speed in client.train.speeds}
                marks[0] = '0'
                marks[client.train.speeds[-1]] = str(int(client.train.speeds[-1]))
            else:
                marks = {}

            incoming = 'Any'  # get_incoming(client.train) if client.train else 'Any'

            if client.train:
                image = f"assets/{client.train.img_path}"
                w, h = fit_image_size(client.train.img_res, 120, 40)
                image_style = {'width': w, 'height': h, 'position': 'absolute', 'top': '90%', 'left': 290/2 - w/2 + 10}
                if control.is_in_reverse(client.train):
                    image_style.update({'-webkit-transform': 'scaleX(-1)', 'transform': 'scaleX(-1)'})
            else:
                image = '?'
                image_style = {}

            return [
                ({} if client.train is not None else {'display': 'none'}),
                label,
                *blocked_trains,
                power_on_disabled,
                max_speed,
                color,
                max_speed,
                marks,
                control.is_power_on(client.train),
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
                    control.set_target_speed(client.train, -target_speed if control.is_in_reverse(client.train) else target_speed)
            if client.train and control.is_emergency_stopping(client.train):
                return -1, False
            if client.train:
                return abs(control.get_target_speed(client.train)), control.get_target_speed(client.train) != 0
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
                    control.accelerate(client.train, 1)
            elif trigger_id == 'decelerate1':
                if client.train:
                    control.accelerate(client.train, -1)
            elif trigger_id == 'stop-train':
                if client.train:
                    control.emergency_stop(client.train)
            return abs(control.get_target_speed(client.train)) if client.train else 0


        # Admin Controls


        @app.callback([Output('admin-status', 'children'),
                       *[Output(f'admin-speedometer-{train.name}', 'value') for train in control.trains],
                       *[Output(f'admin-train-status-{train.name}', 'children') for train in control.trains]],
                      [Input('main-update', 'n_intervals'),
                       Input('admin-checklist', 'value'),
                       Input('power-off-admin', 'n_clicks'),
                       Input('power-on-admin', 'n_clicks'),
                       Input('admin-kill', 'n_clicks'),
                       *[Input(f'admin-stop-{train}', 'n_clicks') for train in control.trains],
                       *[Input(f'admin-kick-{train}', 'n_clicks') for train in control.trains],
                       ])
        def admin_update(_n, checklist, *args):
            trigger = callback_context.triggered[0]
            trigger_id, trigger_prop = trigger["prop_id"].split(".")
            if trigger_id == 'admin-kill':
                control.terminate()
                time.sleep(.5)
                os._exit(0)
            elif trigger_id == 'power-off-admin':
                control.power_off(None)
            elif trigger_id == 'power-on-admin':
                control.power_on(None)
            elif trigger_id.startswith('admin-stop-'):
                train = train_def.TRAINS_BY_NAME[trigger_id[len('admin-stop-'):]]
                control.emergency_stop(train)
            elif trigger_id == 'admin-checklist':
                switches.set_all_locked('lock-all-switches' in checklist)
                control.set_global_speed_limit(100 if 'global-speed-limit' in checklist else None)
                # global _SCHEDULE_MODE
                # _SCHEDULE_MODE = 'schedule-mode' in checklist
                control.set_lights_on('lights-on' in checklist)

            elif trigger_id.startswith('admin-kick-'):
                train = train_def.TRAINS_BY_NAME[trigger_id[len('admin-kick-'):]]
                for client in CLIENTS.values():
                    if client.train == train:
                        control.set_target_speed(train, 0)
                        print("Breaking")
                        client.train = None
                        break
            status = f"""
        * Server: {LOCAL_IP}:{self.port}
        """
        # * {"Switches: ✅ online." if RELAY_ERR is None else f"Switches: ⛔ {RELAY_ERR}"}
            return [status, *[abs(control.get_target_speed(train)) / train.max_speed for train in control.trains],
                    *[status_str(train) for train in control.trains]]


        def status_str(train: train_def.Train):
            label = "◀" if control.is_in_reverse(train) else "▶"
            if control.is_locked(train):
                label += " gesperrt"
            for client in CLIENTS.values():
                if client.train == train:
                    return f"{label} ({'Admin' if client.is_admin else client.addr})"
            return label


        for train in control.trains:
            @app.callback([Output(f'admin-lock-{train}', 'style')], [Input(f'admin-lock-{train}', 'value')])
            def admin_lock_train(locked, train=train):
                locked = bool(locked)
                control.set_locked(train, locked)
                if locked:
                    control.set_target_speed(train, 0)
                raise PreventUpdate()

    def launch(self, port=80):
        self.port = port
        try:
            import bjoern
            print(f"Starting Bjoern server on {LOCAL_IP}, port {port}: http://{LOCAL_IP}:{port}/")
            bjoern.run(self.app.server, port=port, host='0.0.0.0')
        except ImportError:
            try:
                import waitress
                print(f"Starting Waitress server on {LOCAL_IP}, port {port}: http://{LOCAL_IP}:{port}/")
                waitress.serve(self.app.server, port=port)
            except ImportError:
                raise AssertionError(f"Please install 'waitress' or 'bjoern'")
                # print(f"Starting debug server on {LOCAL_IP}, port {PORT}: http://{LOCAL_IP}:{PORT}/")
                # app.run_server(debug=True, host='0.0.0.0', port=PORT)  # this runs the program twice!
        # trains.power_on()

    def clear_inactive_clients(self):
        for client in tuple(CLIENTS.values()):
            if client.is_inactive():
                del CLIENTS[client.user_id]
                if client.train is not None:
                    self.control.set_target_speed(client.train, 0)


def get_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip


LOCAL_IP = get_ip()

