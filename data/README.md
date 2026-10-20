# AirClay recording guide

Example recording: [reference.mp4](reference.mp4).

## Prepare and check your hands

Sit comfortably with steady lighting and a clear background. Keep both wrists and all fingertips visible, with room to move in every direction.

Check the hand labels in the camera preview: raise your physical right hand alone and check for Right; repeat with your left hand and check for Left. Use your body's left and right, not the sides of the screen. If labels are wrong, reposition your hands and check again before collecting data. Do not switch hands to compensate.

Idle means both hands open, relaxed, and back in a comfortable starting position. The default dominant hand is Right; sculpt uses the dominant hand and orbit uses the other hand.

## Start recording

Run these commands from the airclay repository directory. Use the project virtual environment; if it is not ready, follow the setup instructions in the main README first.

First, check framing and hand labels with a short preview:

```bash
.venv/bin/airclay --config configs/record_raw.json track --seconds 20
```

Start a normal session with video:

```bash
.venv/bin/airclay --config configs/record_raw.json record \
  --subject p01 --session s01 \
  --guided --repetitions 20 --prepare-seconds 4 \
  --video --output data
```

Use a unique subject ID for each participant and a different session ID for each session, such as s01 and s02. Existing recordings are never overwritten. Saved sessions go to data/p01_s01/ in this example, not runs/.

A mandatory instruction window opens first. Read its pages and click Continue on the final page to open the camera and begin. The window omits this command section. One session contains 20 accepted rounds, then 2 minutes of natural movement. A complete run saves automatically. The default active recording time is about 9 minutes 45 seconds, plus pauses and retries.

## SCULPT and ORBIT

SCULPT: pinch your dominant hand (Right by default) and move it. Keep the other hand open.

ORBIT: pinch your other hand (Left by default) and move it. Keep the dominant hand open.

Use one continuous pinch during each 4-second action. **There is no fixed movement direction:** vary left, right, up, down, or diagonally across rounds. **Avoid moving in the same direction every time. Use small, smooth movements.**

**Do not return to the starting position while still pinching.** If you approach the frame edge, stop moving and hold the pinch. Wait for OPEN HANDS, then release and return to your starting position.

**You must be back in idle, with both hands open, BEFORE the OPEN HANDS countdown ends.** Do not start the next action early.

## RESIZE

Pinch both hands together. Choose ONE direction for this round: move your hands apart OR bring them closer together. Keep both pinches held throughout the action.

**Do only one expansion or one contraction per round.** Do not repeatedly stretch, move back and forth, or release and pinch again. Alternating apart and together across rounds is fine; both are labeled resize.

For an outward movement, start with your hands a little closer. For an inward movement, start a little farther apart. Stay inside the frame and stop moving when needed. At OPEN HANDS, release and reset to idle before its countdown ends.

## Other prompts

GET READY: use the preparation time (5 seconds by default) to put both open hands in the frame and settle into idle. Wait for the action prompt before pinching.

OPEN HANDS: release the pinch and return to your starting position. You have 2 seconds. Both hands must be open and back in idle before the next prompt.

PAUSED: all three actions in this round are finished. Rest or decide whether to retry. The preview remains live, but pause frames are not recorded.

NATURAL MOVEMENT: for 2 minutes, move naturally without intending to issue editing commands. Relax or stretch your fingers, lower and raise your hands, adjust your posture, or briefly move a hand out of view. Incidental finger contact is fine. Do not deliberately perform sustained pinch-and-move or two-hand resize gestures. This provides idle examples to reduce false activations. Recording saves and ends automatically afterward.

## Interface and recording controls

The top left shows the round, current action, and the next prompt with its countdown. The bottom right shows keyboard controls. Click the camera window to give it keyboard focus.

R: at PAUSED, retry the whole round if it felt wrong. The round number stays the same and preparation starts again. The rejected attempt is excluded from the main recording.

N / Space / Enter: at PAUSED, accept this round and continue. After the final round, this starts preparation for natural movement.

Q / Esc: quit and discard the ENTIRE current recording, including accepted rounds. **Q DOES NOT SAVE.** Do not press it unless you want to exit and start again from round 1 next time. To rest, stay at PAUSED instead. Earlier completed sessions are unaffected.

Let the full guided session finish to save it. Prompt labels are approximate and still need human review after recording.
