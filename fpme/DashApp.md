


## Callbacks

### Page Load server-side

`generate_id` Client registration on page load

`show_admin_controls` on page load

### Triggered server-side

`hide_welcome` on train select

`power_off_admin`

`power_on_admin`

`set_speed_admin`

`admin_checklist_update`

`on_speed_button_pressed`

`speed_update` (coupled to `on_speed_button_pressed` via `speed-control`)


### Periodic server-side (`main-update`)

`main_update`

Handles train switching and power on/off

Outputs
* Controls visibility
* Train label
* Top button Disabled
* Power on Disabled

`display_admin_speeds`


### Periodic Client-side

Speedometer interpolation to target speed