# Stem mode

Skeleton only. The screen shows the four stem labels with the controls disabled, and
the routes return HTTP 501. Do not implement any of the behaviour below in this file's
phase.

- Four per-stem controls changing volume during playback; 0-200 % per stem (100 % = unity)
- Per-stem mute and isolate buttons
- Keys 1-4 select a stem, arrow keys or scroll adjust its volume
- Waveform scrubber with draggable playhead
- Snippet mode: bracket handles, snap to whole seconds, gapless loop
- Export the full song or a snippet at the chosen volumes (WAV, source sample rate)
- Quality modes: Fast and Pro (Pro = 2 shifts, 0.50 overlap)
- Batch folder separation; open a pre-separated stems folder
- Independent stem download
