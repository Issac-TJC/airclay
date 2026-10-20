import numpy as np
import torch
from airclay.learning.models import make_model
from airclay.learning.features import LABELS, FEATURE_DIM, FEATURE_VERSION
from airclay.learning.inference import Predictor
from airclay.learning.evaluate import event_metrics
from airclay.data_tools.synthetic import demo_frames


def test_checkpoint_predictions_match_training_forward(tmp_path):
    torch.manual_seed(42)
    cfg={"hidden":128,"layers":2,"dropout":.2,"window":24,"fps":30}
    frames,_=demo_frames()
    for kind in ("mlp","gru"):
        model=make_model(kind,cfg).eval()
        path=tmp_path/f"{kind}.pt"
        torch.save({"kind":kind,"config":cfg,"feature_version":FEATURE_VERSION,
                    "feature_dim":FEATURE_DIM,"labels":LABELS,"state_dict":model.state_dict()},path)
        predictor=Predictor(path,kind)
        for f in frames[:24]:
            label=predictor.step(f)
        with torch.inference_mode():
            expected=LABELS[model(torch.from_numpy(np.stack(predictor.buffer)).unsqueeze(0)).argmax().item()]
        assert label==expected


def test_event_metrics_identify_misses_and_false_operations():
    import json
    t=list(range(0,1000,100))
    truth=[0,1,1,1,0,0,2,2,0,0]
    pred=[0,0,1,1,0,3,3,0,0,0]
    m=event_metrics(t,truth,pred)
    assert m["missed_operations"]==1 and m["false_operations"]==1
    assert m["onset_delay_ms"]==[100]
    json.dumps(m)


def test_take_boundaries_reset_resampling_and_velocity():
    from airclay.data_tools.synthetic import hand
    from airclay.learning.features import Features, Resampler
    first = {"timestamp_ms": 0, "take_id": "round_01", "hands": {
        "Right": hand(.6, .5), "Left": hand(.3, .5, side="Left")}}
    second = {"timestamp_ms": 50, "take_id": "round_02", "hands": {
        "Right": hand(.8, .5), "Left": hand(.2, .5, side="Left")}}
    resampler, features = Resampler(), Features()
    features.step(resampler.push(first)[0])
    after_pause = resampler.push(second)
    assert len(after_pause) == 1
    assert after_pause[0]["timestamp_ms"] == 50
    assert after_pause[0]["take_id"] == "round_02"
    vector = features.step(after_pause[0])
    np.testing.assert_array_equal(vector[[65, 66, 134, 135, 139]], 0)
    # Actual motion within the new take still produces a velocity.
    next_frame = {**second, "timestamp_ms": 100, "hands": {
        **second["hands"], "Right": hand(.81, .5)}}
    assert features.step(next_frame)[65] > 0


def test_training_windows_do_not_span_accepted_takes(tmp_path):
    import json
    from airclay.data_tools.dataset import Windows
    frames, _ = demo_frames()
    frames = frames[:60]
    for i, frame in enumerate(frames):
        frame["take_id"] = "first" if i < 30 else "second"
    (tmp_path / "metadata.json").write_text(json.dumps({"synthetic": True}))
    (tmp_path / "frames.jsonl").write_text("\n".join(json.dumps(f) for f in frames))
    (tmp_path / "annotations.json").write_text(json.dumps({"verified": True, "segments": [
        {"start_ms": 0, "end_ms": 2000, "label": "idle"}]}))
    windows = Windows([tmp_path], {"window": 24, "fps": 30}, allow_synthetic=True)
    assert len(windows) == 14  # Seven valid windows within each 30-frame take.
    assert [end for _, end in windows.index] == list(range(23, 30)) + list(range(53, 60))


def test_predictor_warms_up_again_after_take_boundary(tmp_path):
    cfg = {"hidden": 16, "layers": 1, "dropout": 0, "window": 24, "fps": 30}
    model = make_model("mlp", cfg).eval()
    path = tmp_path / "model.pt"
    torch.save({"kind": "mlp", "config": cfg, "feature_version": FEATURE_VERSION,
                "feature_dim": FEATURE_DIM, "labels": LABELS, "state_dict": model.state_dict()}, path)
    predictor = Predictor(path, "mlp")
    frames, _ = demo_frames()
    for frame in frames[:24]:
        predictor.step({**frame, "take_id": "first"})
    assert len(predictor.buffer) == 24
    assert predictor.step({**frames[24], "take_id": "second"}) == "idle"
    assert len(predictor.buffer) == 1
