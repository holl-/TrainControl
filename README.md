# Museum Train Control

Run
```shell
sudo python3 fpme/museum_control.py [options]
```

Options:

* `gui`: Show current train positions on map
* `debug`: ignore off-times and do not shut down PC. Shorter stop times. Time dilation if `virtual`.
* `opening`: Silently move trains to ceremony positions and wait for ENTER before continuing.
* `no-sound`: Never switch on train sounds
* `virtual`: Do not output an actual signal. Contacts are disabled. Only for debugging purposes.
* `show`: Do not move trains, only visualize the current positions.