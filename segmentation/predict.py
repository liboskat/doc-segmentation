import glob
import json
import os

import cv2
import numpy as np
import six

from segmentation.data_loader import (
    class_colors,
    get_image_array,
    get_pairs_from_paths,
    get_segmentation_array,
)


def find_latest_checkpoint(checkpoints_path, fail_safe=True):
    def get_epoch_number_from_path(path):
        return path.replace(os.path.normpath(checkpoints_path), "").strip(".")

    # Get all matching files
    all_checkpoint_files = glob.glob(checkpoints_path + ".*")
    if len(all_checkpoint_files) == 0:
        all_checkpoint_files = glob.glob(checkpoints_path + "*.*")
    all_checkpoint_files = [os.path.normpath(f) for f in all_checkpoint_files]
    all_checkpoint_files = [ff.replace(".index", "") for ff in all_checkpoint_files]
    # Filter out entries where the epoc_number part is pure number
    all_checkpoint_files = list(
        filter(lambda f: get_epoch_number_from_path(f).isdigit(), all_checkpoint_files)
    )
    if not len(all_checkpoint_files):
        # The glob list is empty, don't have a checkpoints_path
        if not fail_safe:
            raise ValueError("Checkpoint path {0} invalid".format(checkpoints_path))
        else:
            return None

    # Find the checkpoint file with the maximum epoch
    latest_epoch_checkpoint = max(
        all_checkpoint_files, key=lambda f: int(get_epoch_number_from_path(f))
    )

    return latest_epoch_checkpoint


def model_from_checkpoint_path(checkpoints_path):
    config_path = checkpoints_path + "_config.json"
    assert os.path.isfile(config_path), "Checkpoint config isn't found"

    model_config = json.loads(open(config_path, "r").read())
    latest_weights = find_latest_checkpoint(checkpoints_path)
    assert latest_weights is not None, "Checkpoint weights aren't found"

    from segmentation.models.all_models import model_from_name

    model = model_from_name[model_config["model_class"]](
        model_config["n_classes"],
        input_height=model_config["input_height"],
        input_width=model_config["input_width"],
    )
    print("loaded weights ", latest_weights)
    status = model.load_weights(latest_weights)

    if status is not None:
        status.expect_partial()

    return model


def get_colored_segmentation_image(seg_arr, n_classes, colors=class_colors):
    output_height = seg_arr.shape[0]
    output_width = seg_arr.shape[1]

    seg_img = np.zeros((output_height, output_width, 3))

    for c in range(n_classes):
        seg_arr_c = seg_arr[:, :] == c
        seg_img[:, :, 0] += ((seg_arr_c) * (colors[c][0])).astype("uint8")
        seg_img[:, :, 1] += ((seg_arr_c) * (colors[c][1])).astype("uint8")
        seg_img[:, :, 2] += ((seg_arr_c) * (colors[c][2])).astype("uint8")

    return seg_img


def get_legends(class_names, colors=class_colors):
    n_classes = len(class_names)
    legend = np.zeros(((len(class_names) * 25) + 25, 125, 3), dtype="uint8") + 255

    class_names_colors = enumerate(zip(class_names[:n_classes], colors[:n_classes]))

    for i, (class_name, color) in class_names_colors:
        color = [int(c) for c in color]
        cv2.putText(
            legend,
            class_name,
            (0, (i * 25) + 17),
            cv2.FONT_HERSHEY_COMPLEX,
            0.5,
            (0, 0, 0),
            1,
        )
        cv2.rectangle(legend, (110, (i * 25)), (135, (i * 25) + 25), tuple(color), -1)

    return legend


def overlay_seg_image(inp_img, seg_img):
    orininal_h = inp_img.shape[0]
    orininal_w = inp_img.shape[1]
    seg_img = cv2.resize(
        seg_img, (orininal_w, orininal_h), interpolation=cv2.INTER_NEAREST
    )

    fused_img = (inp_img / 2 + seg_img / 2).astype("uint8")
    return fused_img


def concat_legends(seg_img, legend_img):
    new_h = np.maximum(seg_img.shape[0], legend_img.shape[0])
    new_w = seg_img.shape[1] + legend_img.shape[1]

    out_img = np.zeros((new_h, new_w, 3)).astype("uint8") + legend_img[0, 0, 0]

    out_img[: legend_img.shape[0], : legend_img.shape[1]] = np.copy(legend_img)
    out_img[: seg_img.shape[0], legend_img.shape[1] :] = np.copy(seg_img)

    return out_img


def visualize_segmentation(
    seg_arr,
    inp_img=None,
    n_classes=None,
    colors=class_colors,
    class_names=None,
    overlay_img=False,
    show_legends=False,
    prediction_width=None,
    prediction_height=None,
):
    if n_classes is None:
        n_classes = np.max(seg_arr)

    seg_img = get_colored_segmentation_image(seg_arr, n_classes, colors=colors)

    if inp_img is not None:
        original_h = inp_img.shape[0]
        original_w = inp_img.shape[1]
        seg_img = cv2.resize(
            seg_img, (original_w, original_h), interpolation=cv2.INTER_NEAREST
        )

    if (prediction_height is not None) and (prediction_width is not None):
        seg_img = cv2.resize(
            seg_img,
            (prediction_width, prediction_height),
            interpolation=cv2.INTER_NEAREST,
        )
        if inp_img is not None:
            inp_img = cv2.resize(inp_img, (prediction_width, prediction_height))

    if overlay_img:
        assert inp_img is not None
        seg_img = overlay_seg_image(inp_img, seg_img)

    if show_legends:
        assert class_names is not None
        legend_img = get_legends(class_names, colors=colors)

        seg_img = concat_legends(seg_img, legend_img)

    return seg_img


def predict_segmentation(
    model=None,
    inp=None,
    out_fname=None,
    checkpoints_path=None,
    overlay_img=False,
    class_names=None,
    show_legends=False,
    colors=class_colors,
    prediction_width=None,
    prediction_height=None,
    all_visualisations=False,
    out_fnames=None,
):
    if model is None and (checkpoints_path is not None):
        model = model_from_checkpoint_path(checkpoints_path)

    assert inp is not None
    assert (type(inp) is np.ndarray) or isinstance(
        inp, six.string_types
    ), "Input should be the CV image or the input file name"

    if isinstance(inp, six.string_types):
        inp = cv2.imread(inp, cv2.IMREAD_COLOR)

    assert (
        len(inp.shape) == 3 or len(inp.shape) == 1 or len(inp.shape) == 4
    ), "Image should be h,w,3 "

    output_width = model.output_width
    output_height = model.output_height
    input_width = model.input_width
    input_height = model.input_height
    n_classes = model.n_classes

    x = get_image_array(inp, input_width, input_height)
    pr = model.predict(np.array([x]))[0]
    pr = pr.reshape((output_height, output_width, n_classes)).argmax(axis=2)

    if all_visualisations:
        overlay_and_legends = visualize_segmentation(
            pr,
            inp,
            n_classes=n_classes,
            colors=colors,
            overlay_img=True,
            show_legends=True,
            class_names=class_names,
            prediction_width=prediction_width,
            prediction_height=prediction_height,
        )
        overlay = visualize_segmentation(
            pr,
            inp,
            n_classes=n_classes,
            colors=colors,
            overlay_img=True,
            show_legends=False,
            class_names=class_names,
            prediction_width=prediction_width,
            prediction_height=prediction_height,
        )
        legends = visualize_segmentation(
            pr,
            inp,
            n_classes=n_classes,
            colors=colors,
            overlay_img=False,
            show_legends=True,
            class_names=class_names,
            prediction_width=prediction_width,
            prediction_height=prediction_height,
        )
        plain = visualize_segmentation(
            pr,
            inp,
            n_classes=n_classes,
            colors=colors,
            overlay_img=False,
            show_legends=False,
            class_names=class_names,
            prediction_width=prediction_width,
            prediction_height=prediction_height,
        )
        if out_fnames is not None:
            cv2.imwrite(out_fnames[0], overlay_and_legends)
            cv2.imwrite(out_fnames[1], overlay)
            cv2.imwrite(out_fnames[2], legends)
            cv2.imwrite(out_fnames[3], plain)
    else:
        seg_img = visualize_segmentation(
            pr,
            inp,
            n_classes=n_classes,
            colors=colors,
            overlay_img=overlay_img,
            show_legends=show_legends,
            class_names=class_names,
            prediction_width=prediction_width,
            prediction_height=prediction_height,
        )
        if out_fname is not None:
            cv2.imwrite(out_fname, seg_img)

    return pr


def evaluate_segmentation(
    model=None,
    inp_images=None,
    annotations=None,
    inp_images_dir=None,
    annotations_dir=None,
    checkpoints_path=None,
):
    if model is None:
        assert (
            checkpoints_path is not None
        ), "Please provide the model or the checkpoints_path"
        model = model_from_checkpoint_path(checkpoints_path)

    if inp_images is None:
        assert inp_images_dir is not None, "Please provide inp_images or inp_images_dir"
        assert (
            annotations_dir is not None
        ), "Please provide inp_images or inp_images_dir"

        paths = get_pairs_from_paths(inp_images_dir, annotations_dir)
        paths = list(zip(*paths))
        inp_images = list(paths[0])
        annotations = list(paths[1])

    assert type(inp_images) is list
    assert type(annotations) is list

    tp = np.zeros(model.n_classes)
    fp = np.zeros(model.n_classes)
    fn = np.zeros(model.n_classes)
    n_pixels = np.zeros(model.n_classes)

    for inp, ann in iter(zip(inp_images, annotations)):
        pr = predict_segmentation(model, inp)
        gt = get_segmentation_array(
            ann,
            model.n_classes,
            model.output_width,
            model.output_height,
            no_reshape=True,
        )
        gt = gt.argmax(-1)
        pr = pr.flatten()
        gt = gt.flatten()

        for cl_i in range(model.n_classes):
            tp[cl_i] += np.sum((pr == cl_i) * (gt == cl_i))
            fp[cl_i] += np.sum((pr == cl_i) * ((gt != cl_i)))
            fn[cl_i] += np.sum((pr != cl_i) * ((gt == cl_i)))
            n_pixels[cl_i] += np.sum(gt == cl_i)

    cl_wise_score = tp / (tp + fp + fn + 0.000000000001)
    n_pixels_norm = n_pixels / np.sum(n_pixels)
    frequency_weighted_IU = np.sum(cl_wise_score * n_pixels_norm)
    mean_IU = np.mean(cl_wise_score)

    return {
        "frequency_weighted_IU": frequency_weighted_IU,
        "mean_IU": mean_IU,
        "class_wise_IU": cl_wise_score,
    }
