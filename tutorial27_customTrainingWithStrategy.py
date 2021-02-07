# 210125_https://www.tensorflow.org/tutorials/distribute/custom_training

import tensorflow as tf
import numpy as np
import os

print(tf.__version__)

fashion_mnist = tf.keras.datasets.fashion_mnist
(train_images, train_labels), (test_images, test_labels) = fashion_mnist.load_data()

# 하나의 차원을 배열에 추가 -> 새로운 shape == (28, 28, 1)
# 이렇게 하는 이유는 모델에서 첫 번째 층이 합성곱 층이고, 합성곱 층은 4D 입력을 요구하기 때문
# (batch_size, height, width, channels)
# batch_size 차원은 나중에 추가

train_images = train_images[..., None]
test_images = test_images[..., None]

# 이미지를 [0, 1] 범위로 변경하기
train_images = train_images / np.float32(255)
test_images = test_images / np.float32(255)

# 변수와 그래프를 분산하는 전략 만들기
# 만약 장치들의 목록이 tf.distribute.MirroredStrategy 생성자 안에 명시되어 있지 않다면,
# 자동으로 장치를 인식
strategy = tf.distribute.MirroredStrategy()
print("장치의 수 : {}".format(strategy.num_replicas_in_sync))

# 입력 파이프라인 설정
# 그래프와 변수를 플랫폼과 무관한 SavedModel 형식으로 내보냄. 모델을 내보냈다면, 모델을 불러올 때
# 범위(scope)를 지정해도 되고, 하지 않아도 된다.
BUFFER_SIZE = len(train_images)

BATCH_SIZE_PER_REPLICA = 64
GLOBAL_BATCH_SIZE = BATCH_SIZE_PER_REPLICA * strategy.num_replicas_in_sync

EPOCHS = 10

with strategy.scope():
    train_dataset = tf.data.Dataset.from_tensor_slices((train_images, train_labels)).shuffle(
            BUFFER_SIZE).batch(GLOBAL_BATCH_SIZE)
    train_dist_dataset = strategy.experimental_distribute_dataset(train_dataset)
    
    test_dataset = tf.data.Dataset.from_tensor_slices((test_images, test_labels)).batch(
            GLOBAL_BATCH_SIZE)
    test_dist_dataset = strategy.experimental_distribute_dataset(test_dataset)

# 모델 만들기
# tf.keras.Sequential 을 사용해서 모델 생성
def create_model():
    model = tf.keras.Sequential([
        tf.keras.layers.Conv2D(32, 3, activation = 'relu'),
        tf.keras.layers.MaxPooling2D(),
        tf.keras.layers.Conv2D(64, 3, activation = 'relu'),
        tf.keras.layers.MaxPooling2D(),
        tf.keras.layers.Flatten(),
        tf.keras.layers.Dense(64, activation = 'relu'),
        tf.keras.layers.Dense(10, activation = 'softmax')                
    ])
    return model

# 체크포인드들을 저장하기위한 디렉토리 생성
checkpoint_dir = './training_checkpoints'
checkpoint_prefix = os.path.join(checkpoint_dir, 'ckpt')

# 손실함수 정의하기
# 일반적으로, GPU / CPU 비율이 1인 단일 장치에서 손실은 입력 배치의 샘플 개수로 나누어짐
# tf.distribute.Strategy 를 사용할 때, 4개 GPU 가 있고, 입력 배치 크기가 64라면, 입력 배치 하나가
# 여러 개의 장치(4개의 GPU)에 분배되어, 각 장치는 크기가 16인 입력을 받음
# .....(이해가 안된다...ㅠ)

with strategy.scope():
    # reduction을 'none' 으로 설정하여, 축소를 나중에 하고, GLOBAL_BATCH_SIZE 로 나눔
    loss_object = tf.keras.losses.SparseCategoricalCrossentropy(
            reduction = tf.keras.losses.Reduction.NONE)
    # 또는 loss_fn = tf.keras.losses.sparse_categorical_crossentropy 를 사용해도 됨
    def compute_loss(labels, predictions):
        per_example_loss = loss_object(labels, predictions)
        return tf.nn.compute_average_loss(per_example_loss, global_batch_size = GLOBAL_BATCH_SIZE)

# 손실과 정확도를 기록하기 위한 지표 정의
with strategy.scope():
    test_loss = tf.keras.metrics.Mean(name = 'test_loss')
    train_accuracy = tf.keras.metrics.SparseCategoricalAccuracy(name = 'train_accuracy')
    test_accuracy = tf.keras.metrics.SparseCategoricalAccuracy(name = 'test_accuracy')

# 훈련 루프
# 모델과 옵티마이저는 strategy.scope 에서 만들어져야 함
with strategy.scope():
    model = create_model()
    optimizer = tf.keras.optimizers.Adam()
    checkpoint = tf.train.Checkpoint(optimizer = optimizer, model = model)
    
with strategy.scope():
    def train_step(inputs):
        images, labels = inputs
        
        with tf.GradientTape() as tape:
            predictions = model(images, training = True)
            loss = compute_loss(labels, predictions)
            
        gradients = tape.gradient(loss, model.trainable_variables)
        optimizer.apply_gradients(zip(gradients, model.trainable_variables))
        
        train_accuracy.update_state(labels, predictions)
        return loss
    
    def test_step(inputs):
        images, labels = inputs
        predictions = model(images, training = False)
        t_loss = loss_object(labels, predictions)
        
        test_loss.update_state(t_loss)
        test_accuracy.update_state(labels, predictions)
    
with strategy.scope():
    # experimental_run_v2 는 주어진 계산을 복사하고, 분산된 입력으로 계산을 수행
    @tf.function
    def distributed_train_step(dataset_inputs):
        # per_replica_losses = strategy.experimental_run_v2(train_step, args = (dataset_inputs,))
        # tutorial 에서는 윗 줄로 나오지만, 실행하면 error
        # f3 눌러서 experimental_run_v2 으로 가보면, renamed to run 이라고 써 있어서 아래로 수정  
        per_replica_losses = strategy.run(train_step, args = (dataset_inputs,))
        return strategy.reduce(tf.distribute.ReduceOp.SUM, per_replica_losses, axis = None)
    
    @tf.function
    def distributed_test_step(dataset_inputs):
        return strategy.run(test_step, args = (dataset_inputs,)) # 여기도 experimental_run_v2 > run 
    
    for epoch in range(EPOCHS):
        # 훈련 루프
        total_loss = 0.0
        num_batches = 0
        for x in train_dist_dataset:
            total_loss += distributed_train_step(x)
            num_batches += 1
        train_loss = total_loss / num_batches
        
        # 테스트 루프
        for x in test_dist_dataset:
            distributed_test_step(x)
            
        if epoch % 2 == 0:
            checkpoint.save(checkpoint_prefix)
            
        template = ("에포크 {}, 손실 : {}, 정확도 : {}, 테스트 손실 : {}, 테스트 정확도 : {}")
        print(template.format(epoch + 1, train_loss, train_accuracy.result() * 100, 
                test_loss.result(), test_accuracy.result() * 100))
        test_loss.reset_states()
        train_accuracy.reset_states()
        test_accuracy.reset_states()
            
# 최신 체크포인트를 불러와서 테스트하기 - tf.distribute.Strategy 를 사용해서 체크포인트가 만들어진
# 모델은 전략 사용 여부에 상관없이 불러올 수 있음
eval_accuracy = tf.keras.metrics.SparseCategoricalAccuracy(name = 'eval_accuracy')
new_model = create_model()
new_optimizer = tf.keras.optimizers.Adam()

test_dataset = tf.data.Dataset.from_tensor_slices((test_images, test_labels)).batch(
        GLOBAL_BATCH_SIZE)

@tf.function
def eval_step(images, labels):
    predictions = new_model(images, training = False)
    eval_accuracy(labels, predictions)

checkpoint = tf.train.Checkpoint(optimizer = new_optimizer, model = new_model)
checkpoint.restore(tf.train.latest_checkpoint(checkpoint_dir))

for images, labels in test_dataset:
    eval_step(images, labels)

print("전략을 사용하지 않고, 저장된 모델을 복원한 후의 정확도 : {}".format(
        eval_accuracy.result() * 100))

# 데이터셋에 대해 반복작업을 하는 다른 방법들
# 주어진 스텝의 수에 따라 반복하기를 원하면서 전체 데이터셋을 보는 것을 원치 않는 경우,
# 반복자(iterator) 사용하여 tf.function 외부에서 데이터셋을 반복하는 코드 예제
with strategy.scope():
    for _ in range(EPOCHS):
        total_loss = 0.0
        num_batches = 0
        train_iter = iter(train_dist_dataset)
        
        for _ in range(10):
            total_loss += distributed_train_step(next(train_iter))
            num_batches += 1
        
        average_train_loss = total_loss / num_batches
        
        template = ("에포크 {}, 손실: {}, 정확도 : {}")        
        print(template.format(epoch + 1, average_train_loss, train_accuracy.result() * 100))
        # 위의 라인에서 마지막에 에러남 .. TypeError: 'NoneType' object is not callable
        # 음..? 안날때도 있음
        train_accuracy.reset_states()
        
# tf.function 내부에서 반복하기
# 전체 입력 train_dist_dataset 에 대해, tf.function 내부에서 for x in ... 생성자를 이용하여 반복을
# 하거나, 위에서 사용했던 것처럼 반복자를 사용함으로써 반복할 수 있음
# 아래 예제는 tf.function 으로 한 훈련의 에포크를 감싸고 그 함수에서 train_dist_dataset 을 반복
with strategy.scope():
    @tf.function
    def distributed_train_epoch(dataset):
        total_loss = 0.0
        num_batches = 0
        for x in dataset:
            #per_replica_losses = strategy.experimental_run_v2(train_step, args = (x,))
            per_replica_losses = strategy.run(train_step, args = (x,)) # 여기도 그냥 run
            total_loss += strategy.reduce(tf.distribute.ReduceOp.SUM, per_replica_losses, 
                    axis = None)
            num_batches += 1
        return total_loss / tf.cast(num_batches, dtype = tf.float32)
    
    for epoch in range(EPOCHS):
        train_loss = distributed_train_epoch(train_dist_dataset)
        
        template = ("Epoch {}, Loss: {}, Accuracy: {}")
        print(template.format(epoch + 1, train_loss, train_accuracy.result() * 100))
        
        train_accuracy.reset_states()
        
        