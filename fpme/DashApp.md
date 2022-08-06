


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


### Periodic server-side (`main-update`)

`main_update`

Handles train switching and power on/off

Outputs
* Controls visibility
* Train label
* Top button Disabled
* Power on Disabled

`speed_update` (coupled to `main_update`)

`is_switch_impossible`

`display_admin_speeds`


### Periodic Client-side

Speedometer interpolation to target speed