# Experimental plastic collision

The optional **Plastic collision (experimental)** switch uses Blender Collision
spheres and Soft Body Plasticity to indent the target and retain deformation after
release. It defaults to off and is disabled when a saved file is loaded.

## Try it

1. Save current work and start the demo with `bash scripts/start_blender.sh`.
   The launcher opens a fresh scene.
2. Run `.venv/bin/airclay --config configs/hands.json track --backend rules`.
3. Check the selected target and tracked hands, then enable **Plastic collision
   (experimental)** in the AirClay panel.
4. Place fingertips outside the object before moving them slowly inward.
   **Move unarmed fingers outside clay** means some fingers must leave the object
   before they can participate.
5. Adjust **Collision plane depth** if visible overlap produces no collision.
   Zero is the object's center plane, positive is toward the viewer, and negative
   is away. **Finger collision size** defaults to 1.5. After changing the view,
   depth, front/back setting, or collision size, move fingers outside again.
6. Move away to release. Turning the switch off or stopping the receiver keeps the
   shape. Undo/Redo treats the whole experiment as one operation; **Cancel plastic
   experiment** restores the starting shape.

Contact by an armed fingertip drives deformation; PINCH is only pose feedback.
Hiding the hands, losing tracking, or losing the stream pauses collision and keeps
the current shape. Recovered fingers must move outside before re-entering.
Saving ends the experiment, keeps the shape, and removes temporary solver resources.

## Implementation and limits

- Ten spheres represent fingertips. Palms and finger segments do not collide.
- Targets must be Object Mode surface meshes with no active modifiers, shape keys,
  or shared mesh data. Do not change target topology or transforms during a run.
- An isolated temporary scene runs a low-resolution Soft Body proxy with
  Plasticity=100 and no gravity. The proxy target is about 642 vertices; the demo
  sphere produced 643 in historical tests. Barycentric weights transfer proxy
  displacement to the original mesh without changing its topology.
- A 300-frame solver cache is rebased from the current shape when full. The user's
  scene timeline and object transforms stay fixed. Ending or cancelling removes
  the temporary scene, objects, and meshes.
- Updates are capped at 30 Hz; actual rate depends on solver cost. Excessive solver
  displacement stops the experiment and retains the last stable shape.

This is a soft-body plasticity approximation with manual display depth. It does
not provide calibrated contact, volume conservation, or remeshing, and does not
complete the roadmap's depth or concurrent-control milestones.

## Existing checks

```bash
"$AIRCLAY_BLENDER" --background --factory-startup --python-exit-code 1 --python scripts/test_plasticity.py
"$AIRCLAY_BLENDER" --factory-startup --python-exit-code 1 --python scripts/test_plasticity_gui.py -- --quit
"$AIRCLAY_BLENDER" --background --factory-startup --python-exit-code 1 --python scripts/test_plasticity_load.py
```

The numerical script exercises 330 frames of compression, release, settling, and
cache rebasing. The GUI script uses synthetic input on port 8769 and covers default
off, retained shape, cancel, undo/redo, loss, and save cleanup. The load script checks
cleanup of saved temporary resources and forced disablement. Reports go under
`runs/plasticity/`; inspect JSON `passed:true`, not just process exit. Historical
results are summarized in [VALIDATION.md](VALIDATION.md). Human handling, long-run
stability, and volume changes remain to be measured.
