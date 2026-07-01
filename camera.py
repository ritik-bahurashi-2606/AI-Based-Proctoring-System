from face_detector import get_face_detector, find_faces
from face_landmarks import get_landmark_model, detect_marks
import tensorflow as tf
import numpy as np
import cv2
import base64
from PIL import Image
from io import BytesIO
from tensorflow.keras import Model
from tensorflow.keras.layers import (
    Add, Concatenate, Conv2D, Input, Lambda,
    LeakyReLU, UpSampling2D, ZeroPadding2D, BatchNormalization
)
from tensorflow.keras.regularizers import l2
import math
import os
import time
from collections import deque

# ── Configurable thresholds (env-overridable) ─────────────────────────────────
_HEAD_YAW_THRESH   = float(os.getenv('PROCTOR_HEAD_YAW_THRESHOLD',  '22'))   # degrees
_HEAD_PITCH_THRESH = float(os.getenv('PROCTOR_HEAD_PITCH_THRESHOLD', '18'))   # degrees
_SMOOTHING_ALPHA   = 0.35   # EMA smoothing factor (lower = smoother)
_EAR_BLINK_THRESH  = 0.18   # eye aspect ratio below → blink, skip gaze

# ── Optional gaze tracker ─────────────────────────────────────────────────────
try:
    from gaze_tracking import GazeTracking
    gaze_tracker   = GazeTracking()
    GAZE_AVAILABLE = True
    print("Gaze tracking initialized successfully")
except ImportError as e:
    print(f"Gaze tracking not available: {e}")
    GAZE_AVAILABLE = False
    gaze_tracker   = None

# ── YOLO model ────────────────────────────────────────────────────────────────
import wget

def load_darknet_weights(model, weights_file):
    wf = open(weights_file, 'rb')
    major, minor, revision, seen, _ = np.fromfile(wf, dtype=np.int32, count=5)
    layers = ['yolo_darknet','yolo_conv_0','yolo_output_0',
              'yolo_conv_1','yolo_output_1','yolo_conv_2','yolo_output_2']
    for layer_name in layers:
        sub_model = model.get_layer(layer_name)
        for i, layer in enumerate(sub_model.layers):
            if not layer.name.startswith('conv2d'):
                continue
            batch_norm = None
            if i + 1 < len(sub_model.layers) and \
                    sub_model.layers[i + 1].name.startswith('batch_norm'):
                batch_norm = sub_model.layers[i + 1]
            filters  = layer.filters
            size     = layer.kernel_size[0]
            in_dim   = layer.input_shape[-1]
            if batch_norm is None:
                conv_bias = np.fromfile(wf, dtype=np.float32, count=filters)
            else:
                bn_weights = np.fromfile(wf, dtype=np.float32, count=4*filters)
                bn_weights = bn_weights.reshape((4, filters))[[1, 0, 2, 3]]
            conv_shape   = (filters, in_dim, size, size)
            conv_weights = np.fromfile(wf, dtype=np.float32, count=np.prod(conv_shape))
            conv_weights = conv_weights.reshape(conv_shape).transpose([2, 3, 1, 0])
            if batch_norm is None:
                layer.set_weights([conv_weights, conv_bias])
            else:
                layer.set_weights([conv_weights])
                batch_norm.set_weights(bn_weights)
    assert len(wf.read()) == 0, 'failed to read all data'
    wf.close()


def draw_outputs(img, outputs, class_names):
    boxes, objectness, classes, nums = outputs
    boxes, objectness, classes, nums = boxes[0], objectness[0], classes[0], nums[0]
    wh = np.flip(img.shape[0:2])
    for i in range(nums):
        x1y1 = tuple((np.array(boxes[i][0:2]) * wh).astype(np.int32))
        x2y2 = tuple((np.array(boxes[i][2:4]) * wh).astype(np.int32))
        img = cv2.rectangle(img, x1y1, x2y2, (255, 0, 0), 2)
        img = cv2.putText(img, '{} {:.2f}'.format(
            class_names[int(classes[i])], objectness[i]),
            x1y1, cv2.FONT_HERSHEY_COMPLEX_SMALL, 1, (0, 0, 255), 2)
    return img


yolo_anchors      = np.array([(10,13),(16,30),(33,23),(30,61),(62,45),
                               (59,119),(116,90),(156,198),(373,326)],
                              np.float32) / 416
yolo_anchor_masks = np.array([[6,7,8],[3,4,5],[0,1,2]])


def DarknetConv(x, filters, kernel_size, strides=1, batch_norm=True):
    if strides == 1:
        padding = 'same'
    else:
        x = ZeroPadding2D(((1,0),(1,0)))(x)
        padding = 'valid'
    x = Conv2D(filters=filters, kernel_size=kernel_size, strides=strides,
               padding=padding, use_bias=not batch_norm,
               kernel_regularizer=l2(0.0005))(x)
    if batch_norm:
        x = BatchNormalization()(x)
        x = LeakyReLU(alpha=0.1)(x)
    return x


def DarknetResidual(x, filters):
    prev = x
    x = DarknetConv(x, filters // 2, 1)
    x = DarknetConv(x, filters, 3)
    return Add()([prev, x])


def DarknetBlock(x, filters, blocks):
    x = DarknetConv(x, filters, 3, strides=2)
    for _ in range(blocks):
        x = DarknetResidual(x, filters)
    return x


def Darknet(name=None):
    x = inputs = Input([None, None, 3])
    x = DarknetConv(x, 32, 3)
    x = DarknetBlock(x, 64, 1)
    x = DarknetBlock(x, 128, 2)
    x = x_36 = DarknetBlock(x, 256, 8)
    x = x_61 = DarknetBlock(x, 512, 8)
    x = DarknetBlock(x, 1024, 4)
    return tf.keras.Model(inputs, (x_36, x_61, x), name=name)


def YoloConv(filters, name=None):
    def yolo_conv(x_in):
        if isinstance(x_in, tuple):
            inputs = Input(x_in[0].shape[1:]), Input(x_in[1].shape[1:])
            x, x_skip = inputs
            x = DarknetConv(x, filters, 1)
            x = UpSampling2D(2)(x)
            x = Concatenate()([x, x_skip])
        else:
            x = inputs = Input(x_in.shape[1:])
        x = DarknetConv(x, filters, 1)
        x = DarknetConv(x, filters * 2, 3)
        x = DarknetConv(x, filters, 1)
        x = DarknetConv(x, filters * 2, 3)
        x = DarknetConv(x, filters, 1)
        return Model(inputs, x, name=name)(x_in)
    return yolo_conv


def YoloOutput(filters, anchors, classes, name=None):
    def yolo_output(x_in):
        x = inputs = Input(x_in.shape[1:])
        x = DarknetConv(x, filters * 2, 3)
        x = DarknetConv(x, anchors * (classes + 5), 1, batch_norm=False)
        x = Lambda(lambda x: tf.reshape(x, (-1, tf.shape(x)[1], tf.shape(x)[2],
                                            anchors, classes + 5)))(x)
        return tf.keras.Model(inputs, x, name=name)(x_in)
    return yolo_output


def yolo_boxes(pred, anchors, classes):
    grid_size = tf.shape(pred)[1]
    box_xy, box_wh, objectness, class_probs = tf.split(pred, (2, 2, 1, classes), axis=-1)
    box_xy     = tf.sigmoid(box_xy)
    objectness = tf.sigmoid(objectness)
    class_probs= tf.sigmoid(class_probs)
    pred_box   = tf.concat((box_xy, box_wh), axis=-1)
    grid = tf.meshgrid(tf.range(grid_size), tf.range(grid_size))
    grid = tf.expand_dims(tf.stack(grid, axis=-1), axis=2)
    box_xy  = (box_xy + tf.cast(grid, tf.float32)) / tf.cast(grid_size, tf.float32)
    box_wh  = tf.exp(box_wh) * anchors
    box_x1y1 = box_xy - box_wh / 2
    box_x2y2 = box_xy + box_wh / 2
    bbox = tf.concat([box_x1y1, box_x2y2], axis=-1)
    return bbox, objectness, class_probs, pred_box


def yolo_nms(outputs, anchors, masks, classes):
    b, c, t = [], [], []
    for o in outputs:
        b.append(tf.reshape(o[0], (tf.shape(o[0])[0], -1, tf.shape(o[0])[-1])))
        c.append(tf.reshape(o[1], (tf.shape(o[1])[0], -1, tf.shape(o[1])[-1])))
        t.append(tf.reshape(o[2], (tf.shape(o[2])[0], -1, tf.shape(o[2])[-1])))
    bbox        = tf.concat(b, axis=1)
    confidence  = tf.concat(c, axis=1)
    class_probs = tf.concat(t, axis=1)
    scores      = confidence * class_probs
    boxes, scores, classes, valid_detections = tf.image.combined_non_max_suppression(
        boxes=tf.reshape(bbox, (tf.shape(bbox)[0], -1, 1, 4)),
        scores=tf.reshape(scores, (tf.shape(scores)[0], -1, tf.shape(scores)[-1])),
        max_output_size_per_class=100, max_total_size=100,
        iou_threshold=0.5, score_threshold=0.55)
    return boxes, scores, classes, valid_detections


def YoloV3(size=None, channels=3, anchors=yolo_anchors,
           masks=yolo_anchor_masks, classes=80):
    x = inputs = Input([size, size, channels], name='input')
    x_36, x_61, x = Darknet(name='yolo_darknet')(x)
    x = YoloConv(512, name='yolo_conv_0')(x)
    output_0 = YoloOutput(512, len(masks[0]), classes, name='yolo_output_0')(x)
    x = YoloConv(256, name='yolo_conv_1')((x, x_61))
    output_1 = YoloOutput(256, len(masks[1]), classes, name='yolo_output_1')(x)
    x = YoloConv(128, name='yolo_conv_2')((x, x_36))
    output_2 = YoloOutput(128, len(masks[2]), classes, name='yolo_output_2')(x)
    boxes_0 = Lambda(lambda x: yolo_boxes(x, anchors[masks[0]], classes), name='yolo_boxes_0')(output_0)
    boxes_1 = Lambda(lambda x: yolo_boxes(x, anchors[masks[1]], classes), name='yolo_boxes_1')(output_1)
    boxes_2 = Lambda(lambda x: yolo_boxes(x, anchors[masks[2]], classes), name='yolo_boxes_2')(output_2)
    outputs = Lambda(lambda x: yolo_nms(x, anchors, masks, classes),
                     name='yolo_nms')((boxes_0[:3], boxes_1[:3], boxes_2[:3]))
    return Model(inputs, outputs, name='yolov3')


yolo = YoloV3()
load_darknet_weights(yolo, 'models/yolov3.weights')

# ── Face/landmark models ──────────────────────────────────────────────────────
face_model = get_face_detector(quantized=True)
landmark_model = None
LANDMARK_AVAILABLE = False
try:
    landmark_model = get_landmark_model()
    LANDMARK_AVAILABLE = True
except Exception as e:
    print(f"Landmark model not available: {e}")
    landmark_model = None
    LANDMARK_AVAILABLE = False

# ── Head pose 3-D reference points ───────────────────────────────────────────
_MODEL_POINTS = np.array([
    (0.0,    0.0,    0.0),      # Nose tip
    (0.0,  -330.0, -65.0),      # Chin
    (-225.0, 170.0,-135.0),     # Left eye left corner
    (225.0,  170.0,-135.0),     # Right eye right corner
    (-150.0,-150.0,-125.0),     # Left Mouth corner
    (150.0, -150.0,-125.0)      # Right mouth corner
], dtype=np.float64)

# ── Per-stream EMA smoothing state ───────────────────────────────────────────
# Keyed by Python process (single key fine for single-user proctoring stream)
_smooth_yaw   = None
_smooth_pitch = None
_smooth_roll  = None


def _ema(prev, new_val, alpha=_SMOOTHING_ALPHA):
    """Exponential moving average."""
    if prev is None:
        return float(new_val)
    return alpha * float(new_val) + (1.0 - alpha) * prev


def _rotation_to_euler(rvec):
    """Convert a Rodrigues rotation vector to yaw, pitch, roll in degrees."""
    R, _ = cv2.Rodrigues(rvec)
    # Decompose to Euler angles
    sy = math.sqrt(R[0, 0]**2 + R[1, 0]**2)
    singular = sy < 1e-6
    if not singular:
        pitch = math.degrees(math.atan2(R[2, 1], R[2, 2]))
        yaw   = math.degrees(math.atan2(-R[2, 0], sy))
        roll  = math.degrees(math.atan2(R[1, 0], R[0, 0]))
    else:
        pitch = math.degrees(math.atan2(-R[1, 2], R[1, 1]))
        yaw   = math.degrees(math.atan2(-R[2, 0], sy))
        roll  = 0.0
    return yaw, pitch, roll


def _eye_aspect_ratio(marks, left=True):
    """Return EAR for one eye to detect blinks and suppress false gaze."""
    try:
        if left:
            # dlib landmarks 36-41
            p = [marks[36], marks[37], marks[38], marks[39], marks[40], marks[41]]
        else:
            # dlib landmarks 42-47
            p = [marks[42], marks[43], marks[44], marks[45], marks[46], marks[47]]
        A = np.linalg.norm(np.array(p[1]) - np.array(p[5]))
        B = np.linalg.norm(np.array(p[2]) - np.array(p[4]))
        C = np.linalg.norm(np.array(p[0]) - np.array(p[3]))
        return (A + B) / (2.0 * C) if C > 0 else 0.0
    except Exception:
        return 0.3   # fallback — assume open


def get_frame(imgData):
    global _smooth_yaw, _smooth_pitch, _smooth_roll

    nparr = np.frombuffer(base64.b64decode(imgData), np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    size = image.shape
    focal_length = size[1]
    center       = (size[1] / 2, size[0] / 2)
    camera_matrix = np.array([
        [focal_length, 0,        center[0]],
        [0,        focal_length, center[1]],
        [0,        0,            1        ]
    ], dtype=np.float64)
    dist_coeffs = np.zeros((4, 1))

    # ── YOLO object detection ─────────────────────────────────────────────────
    yolo_input = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    yolo_input = cv2.resize(yolo_input, (320, 320)).astype(np.float32) / 255.0
    yolo_input = np.expand_dims(yolo_input, 0)

    class_names = [c.strip() for c in open("models/classes.TXT").readlines()]
    boxes, scores, classes, nums = yolo(yolo_input)

    count      = 0
    mob_status = 0
    phone_confidence = 0.0

    for i in range(nums[0]):
        cls_id = int(classes[0][i])
        score  = float(scores[0][i])
        if cls_id == 0 and score >= float(os.getenv('YOLO_PERSON_SCORE_MIN', '0.38')):
            count += 1
        if cls_id == 67 and score >= float(os.getenv('YOLO_PHONE_SCORE_MIN', '0.52')):
            mob_status = 1
            phone_confidence = max(phone_confidence, score)

    person_status = 0 if count == 0 else (2 if count > 1 else 1)
    image = draw_outputs(image, (boxes, scores, classes, nums), class_names)

    # Use the original BGR image (not YOLO-scaled) for all subsequent CV ops
    original_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    # ── Head pose estimation ──────────────────────────────────────────────────
    user_move1 = 0   # pitch direction code: 0=normal, 1=up, 2=down
    user_move2 = 0   # yaw direction code:   0=normal, 3=left, 4=right
    head_yaw   = 0.0
    head_pitch = 0.0
    head_roll  = 0.0
    head_confidence = 0.0
    is_blinking = False

    faces = find_faces(original_bgr, face_model)

    if LANDMARK_AVAILABLE and landmark_model is not None and len(faces) > 0:
        face = faces[0]   # use the largest/first face
        try:
            marks = detect_marks(original_bgr, landmark_model, face)
        except Exception as e:
            print(f"Landmark inference failed: {e}")
            marks = None

        if marks is not None and len(marks) >= 55:
            # EAR blink guard ─ suppress gaze/head during blinks
            ear_left  = _eye_aspect_ratio(marks, left=True)
            ear_right = _eye_aspect_ratio(marks, left=False)
            ear_avg   = (ear_left + ear_right) / 2.0
            is_blinking = ear_avg < _EAR_BLINK_THRESH

            image_points = np.array([
                marks[30], marks[8],  marks[36],
                marks[45], marks[48], marks[54]
            ], dtype=np.float64)
        else:
            marks = None
    else:
        marks = None

    if marks is not None:

        success, rvec, tvec = cv2.solvePnP(
            _MODEL_POINTS, image_points, camera_matrix, dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE)

        if success:
            raw_yaw, raw_pitch, raw_roll = _rotation_to_euler(rvec)

            # EMA smoothing to suppress jitter
            _smooth_yaw   = _ema(_smooth_yaw,   raw_yaw)
            _smooth_pitch = _ema(_smooth_pitch, raw_pitch)
            _smooth_roll  = _ema(_smooth_roll,  raw_roll)

            head_yaw   = _smooth_yaw
            head_pitch = _smooth_pitch
            head_roll  = _smooth_roll

            # Confidence = how cleanly the face is detected
            head_confidence = min(1.0, 1.0 - abs(head_yaw) / 90.0)

            # Coded direction values for legacy DB columns + normal_behavior check
            if not is_blinking:
                if head_pitch > _HEAD_PITCH_THRESH:
                    user_move1 = 1   # head up
                elif head_pitch < -_HEAD_PITCH_THRESH:
                    user_move1 = 2   # head down

                if head_yaw < -_HEAD_YAW_THRESH:
                    user_move2 = 3   # head left
                elif head_yaw > _HEAD_YAW_THRESH:
                    user_move2 = 4   # head right
    else:
        # No face → reset smoothing so stale angles don't persist
        _smooth_yaw   = None
        _smooth_pitch = None
        _smooth_roll  = None

    # ── Eye/gaze tracking ─────────────────────────────────────────────────────
    # eye_movements codes:
    # 0 = not detected, 1 = blinking, 2 = center,
    # 3 = left, 4 = right, 5 = up (inferred), 6 = down (inferred)
    eye_movements  = 0
    gaze_confidence = 0.0

    if is_blinking:
        eye_movements = 1    # blink — not a suspicious event

    elif GAZE_AVAILABLE and gaze_tracker is not None:
        try:
            gaze_tracker.refresh(original_bgr)
            if gaze_tracker.is_blinking():
                eye_movements  = 1
                is_blinking    = True
            elif gaze_tracker.is_right():
                eye_movements  = 4
                gaze_confidence = min(1.0, gaze_tracker.horizontal_ratio() or 0.7)
            elif gaze_tracker.is_left():
                eye_movements  = 3
                gaze_confidence = min(1.0, 1.0 - (gaze_tracker.horizontal_ratio() or 0.3))
            elif gaze_tracker.is_center():
                eye_movements  = 2
                gaze_confidence = 0.9
            else:
                eye_movements  = 0
        except Exception as ge:
            print(f"Gaze tracking error: {ge}")
            eye_movements = 0

    # Infer vertical gaze from head pitch when gaze tracker can't detect it
    if eye_movements in (0, 2) and not is_blinking:
        if head_pitch > _HEAD_PITCH_THRESH * 1.1:
            eye_movements  = 5   # looking up
            gaze_confidence = min(1.0, head_pitch / (_HEAD_PITCH_THRESH * 2))
        elif head_pitch < -(_HEAD_PITCH_THRESH * 1.1):
            eye_movements  = 6   # looking down
            gaze_confidence = min(1.0, abs(head_pitch) / (_HEAD_PITCH_THRESH * 2))

    # Fallback: face found but no gaze library
    if not GAZE_AVAILABLE and len(faces) > 0 and eye_movements == 0:
        eye_movements = 2    # assume center

    # ── Annotated JPEG output ─────────────────────────────────────────────────
    ret, jpeg = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 80])
    jpg_as_text = base64.b64encode(jpeg).decode('utf-8')

    return {
        'jpg_as_text':      jpg_as_text,
        'mob_status':       mob_status,
        'phone_confidence': round(phone_confidence, 3),
        'person_status':    person_status,
        'user_move1':       user_move1,
        'user_move2':       user_move2,
        'eye_movements':    eye_movements,
        # ── New fields for proctoring_policy.py ──────────────────────────────
        'head_yaw':         round(head_yaw, 2),
        'head_pitch':       round(head_pitch, 2),
        'head_roll':        round(head_roll, 2),
        'head_confidence':  round(head_confidence, 3),
        'gaze_confidence':  round(gaze_confidence, 3),
        'is_blinking':      bool(is_blinking),
        'face_in_frame_status': 1 if len(faces) > 0 else 0,
        'num_faces':        len(faces),
    }
