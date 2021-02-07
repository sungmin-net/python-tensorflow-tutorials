# https://www.tensorflow.org/tutorials/text/nmt_with_attention

import tensorflow as tf
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from sklearn.model_selection import train_test_split

import unicodedata
import re
import numpy as np
import os
import io
import time

# 데이터셋 다운로드 및 준비
path_to_zip = tf.keras.utils.get_file('spa-eng.zip', 
        origin = 'http://storage.googleapis.com/download.tensorflow.org/data/spa-eng.zip',
        extract = True)
path_to_file = os.path.dirname(path_to_zip) + "/spa-eng/spa.txt"

# 유니코드 파일을 아스키 코드 파일로 변환
def unicode_to_ascii(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def preprocess_sentence(w):
    w = unicode_to_ascii(w.lower().strip())
    
    # 단어와 단어 뒤에 오는 구두점(.) 사이에 공백을 생성
    # 예시 : "he is a boy." => "he is a boy ."
    w = re.sub(r"([?.!,¿])", r" \1 ", w)
    w = re.sub(r'[" "] + ', "", w)
    
    # (a-z, A-Z, ".", "?", "!", ",")을 제어한 모든 것을 공백으로 대체
    w = re.sub(r"[^a-zA-Z?.!,¿]+", " ", w)
    
    w = w.strip()
    
    # 모델이 예측을 시작하거나 중단할 때를 알기 위해서 문장에 start와 end 토큰을 추가
    w = '<start> ' + w + ' <end>'
    return w

en_sentence = u'May I borrow this book?'
sp_sentence = u'¿Puedo tomar prestado este libro?'
print(preprocess_sentence(en_sentence))
print(preprocess_sentence(sp_sentence).encode('utf-8'))

# 1. 문장에 있는 억양 제거
# 2. 불필요한 문자를 제거하여 문장 정리
# 3. 다음과 같은 형식으로 문장의 쌍을 반환 [영어, 스페인어]
def create_dataset(path, num_examples):
    lines = io.open(path, encoding='UTF-8').read().strip().split('\n')
    word_pairs = [[preprocess_sentence(w) for w in l.split('\t')] for l in lines[:num_examples]]
    return zip(*word_pairs)

en, sp = create_dataset(path_to_file, None)
print(en[-1])
print(sp[-1])

def tokenize(lang):
    lang_tokenizer = tf.keras.preprocessing.text.Tokenizer(filters = '')
    lang_tokenizer.fit_on_texts(lang)
    tensor = lang_tokenizer.texts_to_sequences(lang)
    tensor = tf.keras.preprocessing.sequence.pad_sequences(tensor, padding = 'post')
    return tensor, lang_tokenizer

def load_dataset(path, num_examples = None):
    # 전처리된 타겟 문장과 입력 문장 쌍을 생성
    target_lang, input_lang = create_dataset(path, num_examples)
    input_tensor, input_lang_tokenizer = tokenize(input_lang)
    target_tensor, target_lang_tokenizer = tokenize(target_lang)
    
    return input_tensor, target_tensor, input_lang_tokenizer, target_lang_tokenizer

# 더 빠른 실행을 위해 데이터셋의 크기 제한하기(선택)
# 훈련 속도를 높이기 위해 10만개 이상의 문장을 3만개 문장으로 제한(물론, 번역의 질은 저하됨)
# 언어 데이터셋을 아래의 크기로 제한하여 훈련과 검증을 수행
num_examples = 30000
input_tensor, target_tensor, input_lang, target_lang = load_dataset(path_to_file, num_examples)
# 타겟 텐서와 입력 텐서의 최대 길이를 계산
max_length_target, max_length_input = target_tensor.shape[1], input_tensor.shape[1]
# 훈련 집합과 검증 집합을 8:2로 분할
input_tensor_train, input_tensor_val, target_tensor_train, target_tensor_val = train_test_split(
        input_tensor, target_tensor, test_size = 0.2)
# 훈련 집합과 검증 집합의 데이터 크기를 출력
print(len(input_tensor_train), len(target_tensor_train), 
        len(input_tensor_val), len(target_tensor_val))

def convert(lang, tensor):
    for t in tensor:
        if t != 0:
            print("%d ---> %s" % (t, lang.index_word[t]))
            
print("Input Language; index to word mapping")
convert(input_lang, input_tensor_train[0])
print("Target Language; index to word mapping")
convert(target_lang, target_tensor_train[0])

# tf.data 데이터셋 생성
BUFFER_SIZE = len(input_tensor_train)
BATCH_SIZE = 64
steps_per_epoch = len(input_tensor_train) // BATCH_SIZE # '//' 는 나눈 몫을 의미
embedding_dim = 256
units = 1024
vocab_input_size = len(input_lang.word_index) + 1
vocab_target_size = len(target_lang.word_index) + 1
dataset = tf.data.Dataset.from_tensor_slices((input_tensor_train, target_tensor_train)).shuffle(
        BUFFER_SIZE)
dataset = dataset.batch(BATCH_SIZE, drop_remainder = True)
example_input_batch, example_target_batch = next(iter(dataset))
print(example_input_batch.shape, example_target_batch.shape) # print() added

# 인코더 모델과 디코더 모델 쓰기
class Encoder(tf.keras.Model):
    def __init__(self, vocab_size, embedding_dim, enc_units, batch_size):
        super(Encoder, self).__init__()
        self.batch_size = batch_size
        self.enc_units = enc_units
        self.embedding = tf.keras.layers.Embedding(vocab_size, embedding_dim)
        self.gru = tf.keras.layers.GRU(self.enc_units, return_sequences = True, return_state = True,
                recurrent_initializer = 'glorot_uniform')
    
    def call(self, x, hidden):
        x = self.embedding(x)
        output, state = self.gru(x, initial_state = hidden)
        return output, state
    
    def initialize_hidden_state(self):
        return tf.zeros((self.batch_size, self.enc_units))

encoder = Encoder(vocab_input_size, embedding_dim, units, BATCH_SIZE)

# 샘플 입력
sample_hidden = encoder.initialize_hidden_state()
sample_output, sample_hidden = encoder(example_input_batch, sample_hidden)
print('Encoder output shape: (batch size, sequence length, units) {}'.format(sample_output.shape))
print('Encoder hidden state shape: (batch_size, units) {}'.format(sample_hidden.shape))

class BahdanauAttention(tf.keras.layers.Layer):
    def __init__(self, units):
        super(BahdanauAttention, self).__init__()
        self.W1 = tf.keras.layers.Dense(units)
        self.W2 = tf.keras.layers.Dense(units)
        self.V = tf.keras.layers.Dense(1)
    
    def call(self, query, values):
        # 쿼리 은닉 상태는 (batch_size, hidden_size) 쌍으로 이루어짐
        # query_with_time_axis 는 (batch_size, 1, hidden_size) 쌍으로 이루어짐
        # values 는 (batch_size, max_len, hidden_size) 쌍으로 이루어짐
        # 스코어 계산을 위해 덧셈을 수행하고자 시간 축을 확장하여 아래의 과정을 수행
        query_with_time_axis = tf.expand_dims(query, 1)
        
        # score는 (batch_size, max_length, 1) 쌍으로 이루어짐
        # score를 self.V 에 적용하기 때문에 마지막 축에 1을 얻음
        # self.V 에 적용하기 전에 텐서는 (batch_size, max_length, units) 쌍으로 이루어짐
        score = self.V(tf.nn.tanh(self.W1(query_with_time_axis) + self.W2(values)))
        
        # attention_weights 는 (batch_size, max_length, 1) 쌍으로 이루어짐
        attention_weights = tf.nn.softmax(score, axis = 1)
        
        # 덧셈 이후 컨텍스트 벡터는 (batch_size, hidden_size) 쌍으로 이루어짐
        context_vector = attention_weights * values
        context_vector = tf.reduce_sum(context_vector, axis = 1)
        
        return context_vector, attention_weights

attention_layer = BahdanauAttention(10)
attention_result, attention_weights = attention_layer(sample_hidden, sample_output)
print("Attention result shape : (batch_size, units) {}".format(attention_result.shape))
print("Attention weights shape : (batch_size, sequence_length, 1) {}".format(
        attention_weights.shape))

class Decoder(tf.keras.Model):
    def __init__(self, vocab_size, embedding_dim, dec_units, batch_size):
        super(Decoder, self).__init__()
        self.batch_size = batch_size
        self.dec_units = dec_units
        self.embedding = tf.keras.layers.Embedding(vocab_size, embedding_dim)
        self.gru = tf.keras.layers.GRU(self.dec_units, return_sequences = True, return_state = True,
                recurrent_initializer = 'glorot_uniform')
        self.fc = tf.keras.layers.Dense(vocab_size)
        
        # 어텐션 사용
        self.attention = BahdanauAttention(self.dec_units)
        
    def call(self, x, hidden, enc_output):
        # enc_output 은 (batch_size, max_length, hidden_size)쌍으로 이루어져 있음
        context_vector, attention_weights = self.attention(hidden, enc_output)
        
        # 임베딩 층을 통과한 후 x 는 (batch_size, 1, embedding_dim) 쌍으로 이루어져 있음
        x = self.embedding(x)
        
        # 컨텍스트 벡터와 임베딩 결과를 결합한 이후 x 의 형태는 (batch_size, 1, 
        # embedding_dim + hidden_size) 쌍으로 이루어져 있음
        x = tf.concat([tf.expand_dims(context_vector, 1), x], axis = -1)
        
        # 위에 결합된 벡터를 GRU에 전달
        output, state = self.gru(x)
        
        # output은 (batch_size * 1, hidden_size) 쌍으로 이루어져 있음
        output = tf.reshape(output, (-1, output.shape[2]))
        
        # output은 (batch_size, vocab) 쌍으로 이루어져 있음
        x = self.fc(output)
        
        return x, state, attention_weights
    
decoder = Decoder(vocab_target_size, embedding_dim, units, BATCH_SIZE)
sample_decoder_output, _, _ = decoder(tf.random.uniform((BATCH_SIZE, 1)), sample_hidden, 
        sample_output)
print('Decoder output shape : (batch_size, vocab_size) {}'.format(sample_decoder_output.shape))

# 최적화 함수와 손실 함수 정의하기
optimizer = tf.keras.optimizers.Adam()
loss_object = tf.keras.losses.SparseCategoricalCrossentropy(from_logits = True, reduction = 'none')

def loss_function(real, pred):
    mask = tf.math.logical_not(tf.math.equal(real, 0))
    loss_ = loss_object(real, pred)
    
    mask = tf.cast(mask, dtype = loss_.dtype)
    loss_ *= mask
    
    return tf.reduce_mean(loss_)

# 체크포인트(객체 기반 저장)
checkpoint_dir = './training_checkpoints'
checkpoint_prefix = os.path.join(checkpoint_dir, 'ckpt')
checkpoint = tf.train.Checkpoint(optimizer = optimizer, encoder = encoder, decoder = decoder)

# 언어 모델 훈련하기
@tf.function
def train_step(input, target, enc_hidden):
    loss = 0
    with tf.GradientTape() as tape:
        enc_output, enc_hidden = encoder(input, enc_hidden)
        dec_hidden = enc_hidden
        dec_input = tf.expand_dims([target_lang.word_index['<start>']] * BATCH_SIZE, 1)
        # 교사 강요(teacher forcing) - 다음 입력으로 타겟을 피딩(feeding)
        for t in range(1, target.shape[1]):
            # enc_output 을 디코더에 전달
            predictions, dec_hidden, _ = decoder(dec_input, dec_hidden, enc_output)
            loss += loss_function(target[:, t], predictions)
            
            # 교사 강요 사용
            dec_input = tf.expand_dims(target[:, t], 1)
    batch_loss = (loss / int(target.shape[1]))
    variables = encoder.trainable_variables + decoder.trainable_variables
    gradients = tape.gradient(loss, variables)
    optimizer.apply_gradients(zip(gradients, variables))
    return batch_loss

EPOCHS = 10
for epoch in range(EPOCHS):
    start = time.time()
    
    enc_hidden = encoder.initialize_hidden_state()
    total_loss = 0
    
    for (batch, (input, target)) in enumerate(dataset.take(steps_per_epoch)):
        batch_loss = train_step(input, target, enc_hidden)
        total_loss += batch_loss
        
        if batch % 100 == 0:
            print('Epoch {} Batch {} Loss {:.4f}'.format(epoch + 1, batch, batch_loss.numpy()))
    
    # 에포크가 2번 실행될때마다 모델 저장(체크포인트)
    if (epoch + 1) % 2 == 0:
        checkpoint.save(file_prefix = checkpoint_prefix)
    
    print('Epoch {} Loss {:.4f}'.format(epoch + 1, total_loss / steps_per_epoch))
    print('Time taken for 1 epoch {} sec\n'.format(time.time() - start))

# 훈련된 모델로 번역하기
def evaluate(sentence):
    attention_plot = np.zeros((max_length_target, max_length_input))
    sentence = preprocess_sentence(sentence)
    inputs  = [input_lang.word_index[i] for i in sentence.split(' ')]
    inputs = tf.keras.preprocessing.sequence.pad_sequences([inputs], maxlen = max_length_input, 
            padding = 'post')
    inputs = tf.convert_to_tensor(inputs)
    result = ''
    hidden = [tf.zeros((1, units))]
    enc_out, enc_hidden = encoder(inputs, hidden)
    
    dec_hidden = enc_hidden
    dec_input = tf.expand_dims([target_lang.word_index['<start>']], 0)
    for t in range(max_length_target):
        predictions, dec_hidden, attention_weights = decoder(dec_input, dec_hidden, enc_out)
        
        # 나중에 어텐션 가중치를 시각화하기 위해 어텐션 가중치를 저장
        attention_weights = tf.reshape(attention_weights, (-1, ))
        attention_plot[t] = attention_weights.numpy()
        
        predicted_id = tf.argmax(predictions[0]).numpy()
        
        result += target_lang.index_word[predicted_id] + ' '
        if target_lang.index_word[predicted_id] == '<end>':
            return result, sentence, attention_plot
        
        # 예측된 ID를 모델에 다시 피드
        dec_input = tf.expand_dims([predicted_id], 0)
    
    return result, sentence, attention_plot

# 어텐션 가중치를 그리기 위한 함수
def plot_attention(attention, sentence, predicted_sentence):
    fig = plt.figure(figsize = (10, 10))
    ax = fig.add_subplot(1, 1, 1)
    ax.matshow(attention, cmap = 'viridis')
    fontdict = {'fontsize' : 14}
    
    ax.set_xticklabels([''] + sentence, fontdict = fontdict, rotation = 90)
    ax.set_yticklabels([''] + predicted_sentence, fontdict = fontdict)
    
    ax.xaxis.set_major_locator(ticker.MultipleLocator(1))
    ax.yaxis.set_major_locator(ticker.MultipleLocator(1))
    
    plt.show()

def translate(sentence):
    result, sentence, attention_plot = evaluate(sentence)
    print('Input : %s' % (sentence))
    print('Predicted translation: {}'.format(result))
    
    attention_plot = attention_plot[:len(result.split(' ')), :len(sentence.split(' '))]
    plot_attention(attention_plot, sentence.split(' '), result.split(' '))
    
# 마지막 체크포인트를 복원하고 테스트하기
print(checkpoint.restore(tf.train.latest_checkpoint(checkpoint_dir))) # print() added
translate(u'hace mucho frio aqui.')
translate(u'esta es mi vida.')
translate(u'¿todavia estan en casa?')

# 잘못된 번역
translate(u'trata de averiguarlo.')

    
        

            