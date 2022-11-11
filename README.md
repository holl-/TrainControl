# Museum Train Control

Run
```shell
sudo python3 fpme/museum_control.py [options]
```

Options:

* `debug`: ignore off-times and do not shut down PC. Time dilation if `virtual`.
* `opening`: Silently move trains to ceremony positions and wait for ENTER before continuing.
* `no-sound`: Never switch on train sounds
* `virtual`: Do not output an actual signal. Contacts are disabled. Only for debugging purposes.
* `regular`, `fast`, `outside`: Start with this round
* `measure`: Measure time taken by each module