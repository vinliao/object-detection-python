import os
import re
import numpy as np
import cv2
import random
import keras.backend as K
import tensorflow as tf

wider_path = './wider_dataset'
image_path = wider_path + '/WIDER_train/images'
bbox_path = wider_path + '/wider_face_train_bbx_gt.txt'
anchors_path = './yolo_anchors.txt'

def unscale_tensor(tensor, grid_x, grid_y):
    image_size = tf.constant(416.0, dtype=tf.float32)
    x_size = tf.constant(grid_x, dtype=tf.int32)
    y_size = tf.constant(grid_y, dtype=tf.int32)

    #turning the scaled version of bounding box relative to grid to raw form
    #i.e. values relative to grid -> values relative to image

    #matrix: numpy array, each corresponds to x, y, w, h in scaled form
    #grid_x: the x index of grid
    #grid_y: the y index of grid

    size_of_grid = tf.divide(image_size, tf.constant(13.0, dtype=tf.float32))

    x = tf.round(size_of_grid * grid_x) + (size_of_grid * tensor[0])
    y = tf.round(size_of_grid * grid_y) + (size_of_grid * tensor[1])
    w = tensor[2]
    h = tensor[3]

    #x y width height -> top left bottom right
    t = y - (h / 2)
    l = x - (w / 2)
    b = y + (h / 2)
    r = x + (w / 2)

    return tf.constant([t, l, b, r], shape=(4, 1), dtype=tf.int32)

def unscale_bbox(matrix, grid_x, grid_y, format='xywh'):
    #declaring value like this might cause some error
    image_size = 416

    #turning the scaled version of bounding box relative to grid to raw form
    #i.e. values relative to grid -> values relative to image

    #matrix: numpy array, each corresponds to x, y, w, h in scaled form
    #grid_x: the x index of grid
    #grid_y: the y index of grid

    size_of_grid = round(image_size/13, 5)
    x = round(size_of_grid * grid_x) + size_of_grid * matrix[0]
    y = round(size_of_grid * grid_y) + size_of_grid * matrix[1]
    w = matrix[2]
    h = matrix[3]

    if format == 'tlbr':
        return xywh_to_tlbr(x, y, w, h)
    else:
        return np.array((x, y, w, h), dtype=np.uint8)

def xywh_to_tlbr(x, y, w, h):
    #x y width height -> top left bottom right
    t = y - (h / 2)
    l = x - (w / 2)
    b = y + (h / 2)
    r = x + (w / 2)
    return np.array((t, l, b, r), dtype=np.uint8)

def tlbr_to_xywh(t, l, b, r):
    #top left bottom right -> x y width height
    w = r - l
    h = b - t
    x = w / 2
    y = h / 2
    return np.array((x, y, w, h), dtype=np.uint8)

def get_image_names(path_to_img):
    #get all name of the images
    name_list = []
    category = os.listdir(image_path)
    for cat in category:
        img_list = os.listdir(image_path + '/{}'.format(cat))
        for image in img_list:
            name_list.append(image)

    return name_list

def crop_square(image):
    #crop the image from the top left for 1:1 ratio
    smallest = image.shape[0]
    if image.shape[1] < smallest:
        smallest = image.shape[1]

    return image[0:smallest, 0:smallest]

def get_bbox(bbox_raw, image_name):
    #this bbox extraction process only works for wider dataset
    bounding_box = []
    raw_bbox_text = bbox_raw

    #find the bounding box text with the corresponding name
    bbox_of_image = re.findall('{}\n[\n\s\d]+'.format(image_name), raw_bbox_text)[0]
    #clean the bounding box text
    #remove the last number
    bbox_of_image = bbox_of_image[:bbox_of_image.rfind('\n')] 
    #get the bounding box string from the raw text
    bbox_of_image = bbox_of_image[bbox_of_image.find('\n', bbox_of_image.find('\n')):] 
    #remove the count number from bounding box
    bbox_of_image = re.sub('\n\d+\n', '', bbox_of_image)
    bbox_of_image = bbox_of_image.split('\n')

    for one_bbox in bbox_of_image:
        #split the list which is separated by space
        one_bbox = one_bbox.split()
        #take the first four of the list, which are the left top width height respectively
        one_bbox = one_bbox[:4]
        bounding_box.append([int(i) for i in one_bbox])

    return bounding_box

def get_anchors(anchors_raw):
    #it's separated by two spaces
    anchors = anchors_raw.split('  ')

    for i, anchor in enumerate(anchors):
        #cleaning the string
        if anchor[-1] == ',':
            #remove the character ',' if present
            anchors[i] = anchor[:-1]
        if '\n' in anchor:
            #remove the string \n if present
            anchors[i] = re.sub('\n', '', anchor)

        #turning each anchor pairs into list, and casting it into float
        str_anchor = anchors[i].split(',')
        anchors[i] = [float(x) for x in anchors[i].split(',')]

    return anchors

def get_generator(batch_size=32, randomize=True, target=True):
    """
    batch_size: how many items would the generator yield per iteration

    randomize: not generating random data will make sure that we won't yield the same data
    this is useful for the bottleneck because creating bottleneck features only passes the data once.

    target: whether to yield target array--the ground truth bounding box--or not.
    """

    #TODO: this code is pretty dirty, maybe refactor later

    with open(anchors_path, 'r') as f:
        anchors_raw = f.read()

    with open(bbox_path, 'r') as f:
        bbox_raw = f.read()

    #todo: generate data from npy file

    anchors = get_anchors(anchors_raw)
    name_list = get_image_names(image_path)

    #make these np zeros more general
    batch_image = np.zeros((batch_size, 416, 416, 3), dtype=np.uint8)
    if target:
        batch_target = np.zeros((batch_size, 13, 13, len(anchors), 5))

    while True:
        for i in range(batch_size):
            if randomize:
                #select random name from the list
                seed = np.random.choice(len(name_list))
                image_name = name_list[seed]
            else:
                image_name = name_list[i]

            for root, dirs, files in os.walk(image_path):
                for file in files:
                    if image_name in file:
                        image = cv2.imread(root + '/' + image_name)

            image = crop_square(image)
            batch_image[i] = cv2.resize(image, (416, 416))

            if target:
                bounding_box = get_bbox(bbox_raw, image_name)

                #the image here is cropped image, not the resized image
                #if the bbox is outside the cropped image, then it automatically skips
                batch_target[i] = create_target(image, bounding_box, anchors)

        if randomize == False:
            #move the used data to the back of list
            #this is to avoid using the data over and over again
            name_list = name_list[batch_size:] + name_list[:batch_size]

        # print(batch_image[0].shape)
        # print(type(batch_image[0]))
        # test_img = cv2.cvtColor(batch_image[0], cv2.COLOR_BGR2RGB)
        # test_img = Image.fromarray(test_img, 'RGB')
        # print(batch_target[0,:,:,4])
        # test_img.show()


        if target:
            yield batch_image, batch_target
        else:
            yield batch_image

def get_generator_bottleneck(batch_size=32):
    #this is problematic and causes memory error
    data = np.load('bottleneck_data.npz', mmap_mode='r')
    x = data['feature']
    y = data['target']
    print(y.shape)

    #x.shape[1], y.shape[1], ..., x.shape[3], y.shape[3] is the data dimension.
    batch_x = np.zeros((batch_size, x.shape[1], x.shape[2], x.shape[3]))
    batch_y = np.zeros((batch_size, y.shape[1], y.shape[2], y.shape[3], y.shape[4]))

    while True:
        for i in range(batch_size):
            #get seed
            seed = np.random.choice(len(x))
            batch_x[i] = x[seed]
            batch_y[i] = y[seed]
        yield batch_x, batch_y

def get_data(quantity=5):
    with open(anchors_path, 'r') as f:
        anchors_raw = f.read()

    with open(bbox_path, 'r') as f:
        bbox_raw = f.read()

    anchors = get_anchors(anchors_raw)
    name_list = get_image_names(image_path)

    if quantity > 0:
        #use only "quantity" amount of data
        name_list = name_list[:quantity]
    else:
        #use all the data
        quantity = len(name_list)

    #make these np zeros more general
    image_list = np.zeros((quantity, 416, 416, 3), dtype=np.uint8)
    target_list = np.zeros((quantity, 13, 13, 25))

    #randomize the list
    random.shuffle(name_list)
    if quantity > 0:
        name_list = name_list[:quantity]

    for i, image_name in enumerate(name_list):
        #find the image from folder
        for root, dirs, files in os.walk(image_path):
            for file in files:
                if image_name in file:
                    image = cv2.imread(root + '/' + image_name)

        # image_list.append(cv2.resize(image, (416, 416)))
        image = crop_square(image)
        image_list[i] = cv2.resize(image, (416, 416))

        bounding_box = get_bbox(bbox_raw, image_name)
        # target_list.append(create_target(image, bounding_box, anchors))

        #the image here is cropped image, not the resized image
        #if the bbox is outside the cropped image, then it automatically skips
        target_list[i] = create_target(image, bounding_box, anchors)

    return image_list, target_list

def create_target(image, bboxes, anchors, grid_size=13):
    """
    bboxes: ground truth bounding box with [left top width height] information

    anchors: a list of anchors, each elements has a list of two numbers which is the
    width and height of the anchor boxes relative to the grid

    you also need to choose the best place to put these values based on iou values
    """

    img_w, img_h = image.shape[:2]
    image_target = np.zeros((grid_size, grid_size, len(anchors), 5))
    for bbox in bboxes:
        #x1 and y1 are left and top respectively
        left = bbox[0]
        top = bbox[1]
        w = bbox[2]
        h = bbox[3]

        x = int(left+(w/2))
        y = int(top+(h/2))
        bottom = left + w
        right = top + h

        #if bounding box is outside the cropped image, continue
        if left+w > image.shape[0] or top+h > image.shape[1]:
            continue

        #you know, I don't actually have to loop ALL through this thing, I can just get the grid_w and grid_h
        #values from the bounding boxes

        #where the x, y, w, h is relative to the grid and image
        relative_x = x / (float(img_w) / float(grid_size))
        relative_y = y / (float(img_h) / float(grid_size))
        relative_w = w / (float(img_w) / float(grid_size))
        relative_h = h / (float(img_h) / float(grid_size))

        row = int(np.floor(relative_x))
        col = int(np.floor(relative_y))

        #grid_relative_x = relative_x - row
        #grid_relative_y = relative_y - col

        #calculate iou, and place the box on the anchor box with highest iou
        highest_iou = -1
        best_anchor_idx = -1
        for i, anchor in enumerate(anchors):
            bbox = [0, 0, bottom, right]
            anchor_w = anchor[0] * (float(img_w) / float(grid_size))
            anchor_h = anchor[1] * (float(img_h) / float(grid_size))

            anchor_box = [0, 0, anchor_w, anchor_h]
            iou = calculate_IOU(bbox, anchor_box)
            if iou > highest_iou:
                highest_iou = iou
                best_anchor_idx = i

        image_target[col, row, best_anchor_idx, :4] = [relative_x, relative_y, relative_w, relative_h]
        image_target[col, row, best_anchor_idx, 4] = 1.
        #image_target[col, row, best_anchor_idx, 5:] = class

    return image_target

def old_create_target(image, bboxes, anchors, grid_size=13):
    #TODO: coordinate indexing is wrong. x y should be y x
    """
    bboxes: ground truth bounding box with [left top width height] information

    anchors: a list of anchors, each elements has a list of two numbers which is the
    width and height of the anchor boxes relative to the grid
    """

    #image_target = np.zeros((grid_size, grid_size, 5 * len(anchors)))
    image_target = np.zeros((grid_size, grid_size, 5, len(anchors)))
    for bbox in bboxes:
        #x1 and y1 are left and top respectively
        left = bbox[0]
        top = bbox[1]
        w = bbox[2]
        h = bbox[3]

        x = int(left+(w/2))
        y = int(top+(h/2))

        #if bounding box is outside the cropped image, continue
        if left+w > image.shape[0] or top+h > image.shape[1]:
            continue

        #assign value to volume, if the x, y coordinate falls between a value in the grid
        #then assign value on that grid
        for row in range(grid_size):
            #TODO: if this is rounded, the final pixel is losing value
            grid_row = row*image.shape[0]/grid_size
            grid_row_plus = (row+1)*image.shape[0]/grid_size

            for col in range(grid_size):
                grid_col = col*image.shape[1]/grid_size
                grid_col_plus = (col+1)*image.shape[1]/grid_size

                #if the x and y value is inside the grid
                if (x > grid_row and x < grid_row_plus) and\
                        (y > grid_col and y < grid_col_plus):

                    #scaled x and y relative to grid
                    scaled_x = round((x - grid_row) / (grid_row_plus - grid_row), 5)
                    scaled_y = round((y - grid_col) / (grid_col_plus - grid_col), 5)

                    #scaled height and width relative to grid
                    scaled_w = round(w / (grid_row_plus - grid_row), 5)
                    scaled_h = round(h / (grid_col_plus - grid_col), 5)

                    #scale the anchor boxes
                    offset_num = []
                    for anchor_idx, anchor in enumerate(anchors):
                        #ground truth/anchor boxes
                        scaled_anchor_w = scaled_w / anchor[0]
                        scaled_anchor_h = scaled_h / anchor[1]
                        offset_num.append(scaled_anchor_h + scaled_anchor_w)

                        #you can add the class here bro

                        #find the index of the list which has the value closest to 2
                        #the smallest amount of change to a scale is 1, if w or h is scaled by 1 it means
                        #that it doesn't change, and having the least amount of change/offset is the objective.
                        #since there are 2 of them i.e. w and h, we calculate the smallest offset for w and h
                        #hence the number 2 here, which is 1 for w and 1 for h

                        anchor_index = offset_num.index(min(offset_num, key=lambda x:abs(x-2)))
                        best_anchor = anchors[anchor_index]

                        #scalar
                        #the size of ground truths relative to the grid / anchor sizes
                        anchor_scalar_w = scaled_w/best_anchor[0]
                        anchor_scalar_h = scaled_h/best_anchor[1]

                        #size of ground truth bbox = anchors * anchor scales
                        scaled_anchor_w = best_anchor[0]*anchor_scalar_w
                        scaled_anchor_h = best_anchor[1]*anchor_scalar_h

                        image_target[col, row, anchor_idx] = [scaled_x, scaled_y, scaled_anchor_w, scaled_anchor_h, 1]

    return image_target

def create_bbox(target):
    #target is 13x13xdepth, and my depth here is 25
    #if confidence above threshold, show bounding box

    with open(anchors_path, 'r') as f:
        anchors_raw = f.read()
    anchors = get_anchors(anchors_raw)

    grid_size = 13
    bbox_list = []
    num_anchors = 5
    item_per_anchor = 5
    threshold = 0.01
    image_shape = 461

    #maybe I should do non max suppresion
    for row in range(grid_size):
        grid_row = row*image_shape/grid_size
        grid_row_plus = (row+1)*image_shape/grid_size

        for col in range(grid_size):
            grid_col = col*image_shape/grid_size
            grid_col_plus = (col+1)*image_shape/grid_size

            for curr_anchor in range(num_anchors):
                anchor_start = curr_anchor * item_per_anchor
                anchor_end = (curr_anchor+1) * item_per_anchor

                anchor_value = target[col, row, anchor_start:anchor_end]

                if anchor_value[4] > threshold:
                    x = grid_col + anchor_value[0] * (grid_col_plus - grid_col)
                    y = grid_row + anchor_value[1] * (grid_row_plus - grid_row)
                    w = anchors[curr_anchor][0] * anchor_value[2]
                    h = anchors[curr_anchor][1] * anchor_value[3]

                    t, l, b, r = xywh_to_tlbr(x, y, w, h)

                    bbox_list.append([t, l, b, r, anchor_value[4]])

    #return list of bounding boxes on that image
    return bbox_list

def non_max_suppresion():
    pass

def old_calculate_IOU():
    true_y = y_true[..., 1:21:4]
    true_w = y_true[..., 2:22:4]
    true_h = y_true[..., 3:23:4]
    true_conf = y_true[..., 4:24:4]

    pred_x = y_pred[..., 0:20:4]
    pred_y = y_pred[..., 1:21:4]
    pred_w = y_pred[..., 2:22:4]
    pred_h = y_pred[..., 3:23:4]
    pred_conf = y_pred[..., 4:24:4]

    idx = np.where(true_conf == 1)

    #true anchor = (1, 5)
    #probable responsible anchor = (1, 1, 25). Pick the index,
    #but not the anchor box

    #anchor with highest iou = (1, 5)

    true_np_box = np.zeros((len(np_idx), 5)) #bounding box of y_true
    pred_np_box = np.zeros((len(np_idx), 5)) #pred box with highest IOU
    curr_np_box = np.zeros(5) #temp box
    probable_np_box = np.zeros((len(np_idx), 25)) #all the anchor boxes on a grid

    for i, indices in enumerate(np_idx):
        #insert the face(s) anchor box into np array

        #this function is wrong, calculate IOU should take 2 parameters which are
        #true and pred bounding box, each of them on tlbr form

        true_np_box[i, :] = true_x[indices[0], indices[1], indices[2]],\
                            true_y[indices[0], indices[1], indices[2]],\
                            true_w[indices[0], indices[1], indices[2]],\
                            true_h[indices[0], indices[1], indices[2]],\
                            true_conf[indices[0], indices[1], indices[2]]

        probable_np_box[i, :] = pred_x[indices[0], indices[1]],\
                                pred_y[indices[0], indices[1]],\
                                pred_w[indices[0], indices[1]],\
                                pred_h[indices[0], indices[1]],\
                                pred_conf[indices[0], indices[1]]

        #loop through the anchor box, pick the highest iou
        for j in range(5):
            curr_index = np.arange(0+j, 24+j, 5, dtype=np.int32)
            curr_np_box[:] = probable_np_box[curr_index[0],\
                    curr_index[1],\
                    curr_index[2],\
                    curr_index[3],\
                    curr_index[4]]

            #calculate iou between curr_np_box and true_np_box[i]
            #by the way, the shape of the box should be [top left bottom right]
            #instead of [x y w h c]

            #if IOU is the biggest
                #pred_np_box[i, :] = sth, st,h s,th s,th s,ht 

def calculate_IOU(true_bb, pred_bb):
    #true_bb: bounding box with [top left bottom right] format
    #pred_bb: prediction bounding box with [top left bottom right] format

    #determine the intersection of the box
    inter_top = max(true_bb[0], pred_bb[0])
    inter_left = max(true_bb[1], pred_bb[1])
    inter_bottom = min(true_bb[2], pred_bb[2])
    inter_right = min(true_bb[3], pred_bb[3])

    if inter_top > inter_bottom or inter_left > inter_right:
        #if there is no intersection, iou becomes 0
        return 0.0

    #calculate the area of rectangle
    intersection_area = (inter_bottom - inter_top) * (inter_right - inter_left)
    true_bb_area = (true_bb[2] - true_bb[0]) * (true_bb[3] - true_bb[1])
    pred_bb_area = (pred_bb[2] - pred_bb[0]) * (pred_bb[3] - pred_bb[1])

    #calculate the iou, dividing area of overlap by area of union
    iou = intersection_area / float(true_bb_area + pred_bb_area - intersection_area)

    if iou <= 1.0 and iou >= 0.0:
        return iou
    else:
        raise ValueError('Incorrect IOU value: %d' %(iou))

def old_calculate_tensor_IOU(true_bb, pred_bb):
    print('TRUE BB:', true_bb)
    print('PRED BB:', pred_bb)
    #true_bb: ground truth tensor with [top left bottom right] format
    #pred_bb: prediction tensor with [top left bottom right] format

    #determine the intersection of the box
    inter_top = tf.maximum(true_bb[0], pred_bb[0])
    inter_left = tf.maximum(true_bb[1], pred_bb[1])
    inter_bottom = tf.minimum(true_bb[2], pred_bb[2])
    inter_right = tf.minimum(true_bb[3], pred_bb[3])

    """
    The tf.cond below is equivalent with

    if inter_top > inter_bottom or inter_left > inter_right:
        return 0.0
    """
    def f1():
        print('F1')
        return tf.constant(0.0, dtype=tf.float32)
    def f2():
        print('F2')
        return tf.constant(-1.0, dtype=tf.float32)
    tf.cond(tf.logical_or(tf.greater(inter_top, inter_bottom), tf.greater(inter_left, inter_right)),\
            #true_fn=lambda: tf.constant(0.0, dtype=tf.float32),\
            true_fn=f1,\
            #false_fn=lambda: tf.constant(-1.0, dtype=tf.float32))
            false_fn=f2)

    #TODO: this is a structure of normal programming, I will try changing it more like a tensorflow like
    #structure, I'll change it so that I only have 1 tf.cond

    #calculate the area of rectangle
    intersection_area = tf.multiply(tf.subtract(inter_top, inter_bottom), tf.subtract(inter_right, inter_left))
    true_bb_area = tf.multiply(tf.subtract(true_bb[0], true_bb[2]), tf.subtract(true_bb[1], true_bb[3]))
    pred_bb_area = tf.multiply(tf.subtract(pred_bb[0], pred_bb[2]), tf.subtract(pred_bb[1], pred_bb[3]))

    #iou is calculated by dividing the intersection area, with area of union
    #area of union = true_bb_area + pred_bb_area - intersection_area
    iou = tf.divide(intersection_area, tf.subtract(tf.add(true_bb_area,\
            pred_bb_area), intersection_area))
    iou = tf.cast(iou, dtype=tf.float32) #casting from tf.float64 to tf.float32
    #TODO: when i checked, iou is a negative value (wtf)
    print(K.eval(iou))

    """
    The tf.cond below is equivalent with

    if iou < 1.0 and iou > 0.0:
        return iou
    else:
        raise ValueError('Incorrect IOU value: %d' %(iou))
    """
    def f3():
        print('F3')
        return iou
    def f4():
        print('F4')
        return tf.constant(-1.0, dtype=tf.float32)

    tf.cond(tf.logical_and(tf.greater(iou, tf.constant(0.0)),\
            tf.greater(tf.constant(1.0), iou)),\
            #true_fn=lambda: iou,\
            true_fn=f3,\
            #false_fn=lambda: tf.constant(-1.0, dtype=tf.float32))
            false_fn=f4)

def calculate_tensor_IOU(true_bb, pred_bb):
    #true_bb: ground truth tensor with [top left bottom right] format
    #pred_bb: prediction tensor with [top left bottom right] format

    #determine the intersection of the box
    inter_top = tf.maximum(true_bb[0], pred_bb[0])
    inter_left = tf.maximum(true_bb[1], pred_bb[1])
    inter_bottom = tf.minimum(true_bb[2], pred_bb[2])
    inter_right = tf.minimum(true_bb[3], pred_bb[3])

    """
    The tf.cond below is equivalent with

    if inter_top > inter_bottom or inter_left > inter_right:
        return 0.0
    """
    #iou = tf.cond(tf.logical_or(tf.greater(inter_top, inter_bottom), tf.greater(inter_left, inter_right)),\
    #        true_fn=lambda: tf.constant(0.0, dtype=tf.float32),\
    #        false_fn=lambda: tf.constant(-1.0, dtype=tf.float32))

    #calculate the area of rectangle
    intersection_area = tf.multiply(tf.subtract(inter_top, inter_bottom), tf.subtract(inter_right, inter_left))
    true_bb_area = tf.multiply(tf.subtract(true_bb[0], true_bb[2]), tf.subtract(true_bb[1], true_bb[3]))
    pred_bb_area = tf.multiply(tf.subtract(pred_bb[0], pred_bb[2]), tf.subtract(pred_bb[1], pred_bb[3]))

    #iou is calculated by dividing the intersection area, with area of union
    #area of union = true_bb_area + pred_bb_area - intersection_area

    #if there is no intersection between the two bb, intersection area is 0
    iou = tf.divide(intersection_area, tf.subtract(tf.add(true_bb_area, pred_bb_area), intersection_area))
    iou = tf.cast(iou, dtype=tf.float32) #casting from tf.float64 to tf.float32

    """
    The tf.cond below is equivalent with

    if iou < 1.0 and iou > 0.0:
        return iou
    else:
        raise ValueError('Incorrect IOU value: %d' %(iou))
    """

    #tf.cond(tf.logical_and(tf.greater(iou, tf.constant(0.0)),\
    #        tf.greater(tf.constant(1.0), iou)),\
    #        true_fn=lambda: iou,\
    #        false_fn=lambda: tf.constant(-1.0, dtype=tf.float32))

    #tf cond is not returning any value back to my loss function. the return of tf.cond can be stored in a 
    #variable, but to return a value to the loss function, I need to explicitly return it.
    iou = tf.clip_by_value(iou, 0.0, 1.0)
    return iou

    #create some if condition here

