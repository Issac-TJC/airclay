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
