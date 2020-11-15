from typing import List
from typing import Union

from realtimenet.camera import VideoSource
from realtimenet.camera import VideoStream
from realtimenet.display import DisplayResults
from realtimenet.engine import InferenceEngine
from realtimenet.downstream_tasks.postprocess import PostProcessor

import cv2
import numpy as np
import torch.nn as nn


class Controller:

    def __init__(
            self,
            neural_network: nn.Module,
            post_processors: Union[PostProcessor, List[PostProcessor]],
            results_display: DisplayResults,
            camera_id: int,
            path_in: str = None,
            path_out: str = None,
            use_gpu: bool = True):

        video_source = VideoSource(
            camera_id=camera_id,
            size=self.inference_engine.expected_frame_size,
            filename=path_in
        )
        self.video_stream = VideoStream(video_source, self.inference_engine.fps)
        self.inference_engine = InferenceEngine(neural_network, use_gpu=use_gpu)
        self.postprocessors = post_processors
        self.results_display = results_display
        self.path_out = path_out
        self.video_recorder = None  # created in `display_prediction`
        self.video_recorder_raw = None  # created in `display_prediction`

    def run_inference(self):
        clip = np.random.randn(1, self.inference_engine.step_size, self.inference_engine.expected_frame_size[0],
                               self.inference_engine.expected_frame_size[1], 3)

        frame_index = 0
        runtime_error = None

        self._start_inference()

        while True:
            try:
                frame_index += 1

                # Grab frame if possible
                img_tuple = self.video_stream.get_image()
                # If not possible, stop
                if img_tuple is None:
                    break

                # Unpack
                img, numpy_img = img_tuple

                clip = np.roll(clip, -1, 1)
                clip[:, -1, :, :, :] = numpy_img

                if frame_index == self.inference_engine.step_size:
                    # A new clip is ready
                    self.inference_engine.put_nowait(clip)

                frame_index = frame_index % self.inference_engine.step_size

                # Get predictions
                prediction = self.inference_engine.get_nowait()

                prediction_postprocessed = self.postprocess_prediction(prediction)

                self.display_prediction(img, prediction_postprocessed)

            except Exception as runtime_error:
                break

            # Press escape to exit
            if cv2.waitKey(1) == 27:
                break

        self._stop_inference()

        if runtime_error:
            raise runtime_error

    def postprocess_prediction(self, prediction):
        post_processed_data = {}
        for post_processor in self.postprocessors:
            post_processed_data.update(post_processor(prediction))
        return {'prediction': prediction, **post_processed_data}

    def display_prediction(self, img: np.ndarray, prediction_postprocessed: dict):
        # Live display
        img_augmented = self.results_display.show(img, prediction_postprocessed)

        # Recording
        if self.path_out:
            if self.video_recorder is None or self.video_recorder_raw is None:
                self._instantiate_video_recorders(img_augmented, img)

            self.video_recorder.write(img_augmented)
            self.video_recorder_raw.write(img)

    def _start_inference(self):
        print("Starting inference")
        self.inference_engine.start()
        self.video_stream.start()

    def _stop_inference(self):
        print("Stopping inference")
        cv2.destroyAllWindows()
        self.video_stream.stop()
        self.inference_engine.stop()

        if self.video_recorder is not None:
            self.video_recorder.release()

        if self.video_recorder_raw is not None:
            self.video_recorder_raw.release()

    def _instantiate_video_recorders(self, img_augmented, img_raw):
        self.video_recorder = cv2.VideoWriter(self.path_out, 0x7634706d, self.inference_engine.fps,
                                              (img_augmented.shape[1], img_augmented.shape[0]))

        path_raw = self.path_out.replace('.mp4', '_raw.mp4')
        self.video_recorder_raw = cv2.VideoWriter(path_raw, 0x7634706d, self.inference_engine.fps,
                                                  (img_raw.shape[1], img_raw.shape[0]))