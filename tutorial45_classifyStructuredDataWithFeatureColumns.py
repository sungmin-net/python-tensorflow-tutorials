# https://www.tensorflow.org/tutorials/structured_data/feature_columns
# 한글판은 링크에 자료가 없음
# 영문판으로 진행...도 중간에 막힘. Python int too large to convert to C long


import numpy as np
import pandas as pd

import tensorflow as tf
from tensorflow import feature_column
from tensorflow.keras import layers
from sklearn.model_selection import train_test_split

# Use Pandas to create a dataframe
import pathlib

dataset_url = 'http://storage.googleapis.com/download.tensorflow.org/data/petfinder-mini.zip'
csv_file = 'datasets/petfinder-mini/petfinder-mini.csv'

tf.keras.utils.get_file('petfinder_mini.zip', dataset_url, extract = True, cache_dir='.')
dataframe = pd.read_csv(csv_file)
 
print(dataframe.head()) # print() added

# Crate target variable

# In the original dataset "4" indicates the pet was not adopted.
dataframe['target'] = np.where(dataframe['AdoptionSpeed'] == 4, 0, 1)

# Drop un-used columns
dataframe = dataframe.drop(columns = ['AdoptionSpeed', 'Description'])

# Split the dataframe into train, validation, and test
train, test = train_test_split(dataframe, test_size = 0.2)
train, val = train_test_split(train, test_size = 0.2)
print(len(train), 'train examples')
print(len(val), 'validation examples')
print(len(test), 'test examples')

# Create an input pipeline using tf.data
# A utility method to create a tf.data dataset from a Pandas Dataframe
def df_to_dataset(dataframe, shuffle = True, batch_size = 32):
    dataframe = dataframe.copy()
    labels = dataframe.pop('target')
    ds = tf.data.Dataset.from_tensor_slices((dict(dataframe), labels))
    if shuffle:
        ds = ds.shuffle(buffer_size = len(dataframe))
    ds = ds.batch(batch_size)
    return ds

batch_size = 5
train_ds = df_to_dataset(train, batch_size = batch_size)
val_ds = df_to_dataset(val, shuffle = False, batch_size = batch_size)
test_ds = df_to_dataset(test, shuffle = False, batch_size = batch_size)

# Understand the input pipeline
for feature_batch, label_batch in train_ds.take(1):
    print('Every feature : ', list(feature_batch.keys()))
    print('A batch of ages : ', feature_batch['Age'])
    print('A batch of targets : ', label_batch)

# Demonstrate several types of feature columns
# We will use this batch to demonstrate several types of feature columns
example_batch = next(iter(train_ds))[0]

# A utility method to create a feature column and to transform a batch of date
def demo(feature_column):
    feature_layer = layers.DenseFeatures(feature_column)
    print(feature_layer(example_batch).numpy())
    
# Numeric columns
photo_count = feature_column.numeric_column('PhotoAmt')
demo(photo_count)

# Bucketized columns
age = feature_column.numeric_column('Age')
age_buckets = feature_column.bucketized_column(age, boundaries = [1, 3, 5])
demo(age_buckets)

# Categorical columns
animal_type = feature_column.categorical_column_with_vocabulary_list('Type', ['Cat', 'Dog'])
animal_type_one_hot = feature_column.indicator_column(animal_type)
demo(animal_type_one_hot)

# Notice the input to the embedding column is the categorical column we previously created
breed1 = feature_column.categorical_column_with_vocabulary_list('Breed1', dataframe.Breed1.unique())
breed1_embedding = feature_column.embedding_column(breed1, dimension = 8)
demo(breed1_embedding)

# Hashed feature columns
breed1_hashed = feature_column.categorical_column_with_hash_bucket('Breed1', hash_bucket_size = 10)
demo(feature_column.indicator_column(breed1_hashed))


# Crossed feature columns
crossed_feature = feature_column.crossed_column([age_buckets, animal_type], hash_bucket_size = 10)
demo(feature_column.indicator_column(crossed_feature))
# 위 라인에서 죽음.. 어흐... OverflowError: Python int too large to convert to C long
# 어떻게 고쳐햐 하나..

# Choose which columns to use
feature_columns = []

# numeric cols
for header in ['PhotoAmt', 'Fee', 'Age']:
    feature_columns.append(feature_column.numeric_column(header))

# bucketized cols
age = feature_column.numeric_column('Age')
age_buckets = feature_column.bucketized_column(age, boundaries = [1, 2, 3, 4, 5])
feature_columns.append(age_buckets)

# indicator_columns
indicator_column_names = ['Type', 'Color1', 'Color2', 'Gender', 'MaturitySize', 'FurLength',
        'Vaccinated', 'Sterilized', 'Health']
for col_name in indicator_column_names:
    categorical_column = feature_column.categorical_column_with_vocabulary_list(cal_name,
            dataframe[col_name].unique())
    indicator_column = feature_column.indicator_column(categorical_column)
    feature_columns.append(indicator_column)

# embedding columns
breed1 = feature_column.categorical_column_with_vocabulary_list('Breed1', dataframe.Breed1.unique())
breed1_embedding = feature_column.embedding_column(breed1, dimension = 8)
feature_columns.append(breed1_embedding)

# crossed columns
age_type_feature = feature_column_crossed_column([age_buckets, animal_type], hash_bucket_size = 100)
feature_columns.append(feature_column.indicator_column(age_type_feature))

# Create a feature layer
batch_size = 32
train_ds = df_to_dataset(train, batch_size = batch_size)
val_ds = df_to_dataset(val, shuffle = False, batch_size = batch_size)
test_ds = df_to_dataset(test, shuffle = False, batch_size = batch_size)

# Create, compile, and train the model
feature_layer = tf.keras.layers.DenseFeatures(feature_columns)
model = tf.keras.Sequential([
    feature_layer,
    layers.Dense(128, activation = 'relu'),
    layers.Dense(128, activation = 'relu'),
    layers.Dropout(.1),
    layers.Dense(1)    
])

model.compile(optimizer = 'adam', loss = tf.keras.losses.BinaryCrossentropy(from_logits = True),
        metrics = ['accuracy'])
model.fit(train_ds, validation_data = val_ds, epochs = 10)
loss, accuracy = model.evaluate(test_ds)
print("Accuracy", accuracy)
