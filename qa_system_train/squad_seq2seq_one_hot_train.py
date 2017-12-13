from keras.models import Model
from keras.layers import add, Dropout, RepeatVector
from keras.layers.recurrent import LSTM
from keras.layers import Dense, Input, Embedding
from keras.preprocessing.sequence import pad_sequences
from collections import Counter
import nltk
import numpy as np
from sklearn.model_selection import train_test_split
from keras.callbacks import ModelCheckpoint
import json

np.random.seed(42)

BATCH_SIZE = 64
NUM_EPOCHS = 10
EMBED_HIDDEN_UNITS = 64
HIDDEN_UNITS = 256
MAX_DATA_COUNT = 5000
MAX_CONTEXT_SEQ_LENGTH = 300
MAX_QUESTION_SEQ_LENGTH = 60
MAX_TARGET_SEQ_LENGTH = 50
MAX_VOCAB_SIZE = 10000
MODEL_DIR = 'models/SQuAD'
DATA_PATH = 'data/SQuAD/train-v1.1.json'
WEIGHT_FILE_PATH = MODEL_DIR + '/word-weights.h5'

context_counter = Counter()
question_counter = Counter()
ans_counter = Counter()

context_max_seq_length = 0
question_max_seq_length = 0
ans_max_seq_length = 0

whitelist = 'abcdefghijklmnopqrstuvwxyz1234567890,.?'


def in_white_list(_word):
    for char in _word:
        if char in whitelist:
            return True

    return False


data = []
with open(DATA_PATH) as file:
    json_data = json.load(file)

    for instance in json_data['data']:
        for paragraph in instance['paragraphs']:
            context = [w.lower() for w in nltk.word_tokenize(paragraph['context']) if in_white_list(w)]
            if len(context) > MAX_CONTEXT_SEQ_LENGTH:
                continue
            qas = paragraph['qas']
            for qas_instance in qas:
                question = [w.lower() for w in nltk.word_tokenize(qas_instance['question']) if in_white_list(w)]
                if len(question) > MAX_QUESTION_SEQ_LENGTH:
                    continue
                answers = qas_instance['answers']
                for answer in answers:
                    ans = [w.lower() for w in nltk.word_tokenize(answer['text']) if in_white_list(w)]
                    ans = ['START'] + ans + ['END']
                    if len(ans) > MAX_TARGET_SEQ_LENGTH:
                        continue
                    if len(data) < MAX_DATA_COUNT:
                        data.append((context, question, ans))
                        for w in context:
                            context_counter[w] += 1
                        for w in question:
                            question_counter[w] += 1
                        for w in ans:
                            ans_counter[w] += 1
                        context_max_seq_length = max(context_max_seq_length, len(context))
                        question_max_seq_length = max(question_max_seq_length, len(question))
                        ans_max_seq_length = max(ans_max_seq_length, len(ans))
        if len(data) >= MAX_DATA_COUNT:
            break

context_word2idx = dict()
question_word2idx = dict()
ans_word2idx = dict()
for idx, word in enumerate(question_counter.most_common(MAX_VOCAB_SIZE)):
    question_word2idx[word[0]] = idx + 2
for idx, word in enumerate(context_counter.most_common(MAX_VOCAB_SIZE)):
    context_word2idx[word[0]] = idx + 2
for idx, word in enumerate(ans_counter.most_common(MAX_VOCAB_SIZE)):
    ans_word2idx[word[0]] = idx + 1

context_word2idx['PAD'] = 0
context_word2idx['UNK'] = 1
question_word2idx['PAD'] = 0
question_word2idx['UNK'] = 1
ans_word2idx['UNK'] = 0

context_idx2word = dict([(idx, word) for word, idx in context_word2idx.items()])
question_idx2word = dict([(idx, word) for word, idx in question_word2idx.items()])
ans_idx2word = dict([(idx, word) for word, idx in ans_word2idx.items()])

num_context_tokens = len(context_idx2word)
num_question_tokens = len(question_idx2word)
num_decoder_tokens = len(ans_idx2word)

np.save(MODEL_DIR + '/word-context-word2idx.npy', context_word2idx)
np.save(MODEL_DIR + '/word-context-idx2word.npy', context_idx2word)
np.save(MODEL_DIR + '/word-question-word2idx.npy', question_word2idx)
np.save(MODEL_DIR + '/word-question-idx2word.npy', question_idx2word)
np.save(MODEL_DIR + '/word-ans-word2idx.npy', ans_word2idx)
np.save(MODEL_DIR + '/word-ans-idx2word.npy', ans_idx2word)

config = dict()
config['num_context_tokens'] = num_context_tokens
config['num_question_tokens'] = num_question_tokens
config['num_decoder_tokens'] = num_decoder_tokens
config['context_max_seq_length'] = context_max_seq_length
config['question_max_seq_length'] = question_max_seq_length
config['ans_max_seq_length'] = ans_max_seq_length

print(config)
np.save(MODEL_DIR + '/word-squad-context.npy', config)


def generate_batch(source):
    num_batches = len(source) // BATCH_SIZE
    while True:
        for batchIdx in range(0, num_batches):
            start = batchIdx * BATCH_SIZE
            end = (batchIdx + 1) * BATCH_SIZE
            source_batch = source[start:end]
            context_data_batch = []
            question_data_batch = []
            ans_data_batch = []
            for (_context, _question, _ans) in source_batch:
                context_wids = []
                question_wids = []
                ans_wids = []
                for w in _context:
                    wid = 1
                    if w in context_word2idx:
                        wid = context_word2idx[w]
                    context_wids.append(wid)
                for w in _question:
                    wid = 1
                    if w in question_word2idx:
                        wid = question_word2idx[w]
                    question_wids.append(wid)
                for w in _ans:
                    wid = 0
                    if w in ans_word2idx:
                        wid = ans_word2idx[w]
                    ans_wids.append(wid)
                context_data_batch.append(context_wids)
                question_data_batch.append(question_wids)
                ans_data_batch.append(ans_wids)
            context_data_batch = pad_sequences(context_data_batch, context_max_seq_length)
            question_data_batch = pad_sequences(question_data_batch, question_max_seq_length)

            decoder_target_data_batch = np.zeros(shape=(BATCH_SIZE, ans_max_seq_length, num_decoder_tokens))
            decoder_input_data_batch = np.zeros(shape=(BATCH_SIZE, ans_max_seq_length, num_decoder_tokens))
            for lineIdx, ans_wids in enumerate(ans_data_batch):
                for idx, w2idx in enumerate(ans_wids):
                    decoder_input_data_batch[lineIdx, idx, w2idx] = 1
                    if idx > 0:
                        decoder_target_data_batch[lineIdx, idx - 1, w2idx] = 1
            yield [context_data_batch, question_data_batch, decoder_input_data_batch], decoder_target_data_batch


context_inputs = Input(shape=(None,), name='context_inputs')
encoded_context = Embedding(input_dim=num_context_tokens, output_dim=EMBED_HIDDEN_UNITS,
                            input_length=context_max_seq_length, name='context_embedding')(context_inputs)
encoded_context = Dropout(0.3)(encoded_context)

question_inputs = Input(shape=(None,), name='question_inputs')
encoded_question = Embedding(input_dim=num_question_tokens, output_dim=EMBED_HIDDEN_UNITS,
                             input_length=question_max_seq_length, name='question_embedding')(question_inputs)
encoded_question = Dropout(0.3)(encoded_question)
encoded_question = LSTM(units=EMBED_HIDDEN_UNITS, name='question_lstm')(encoded_question)
encoded_question = RepeatVector(context_max_seq_length)(encoded_question)

merged = add([encoded_context, encoded_question])
encoder_outputs, encoder_state_h, encoder_state_c = LSTM(units=HIDDEN_UNITS,
                                                         name='encoder_lstm', return_state=True)(merged)

encoder_states = [encoder_state_h, encoder_state_c]

decoder_inputs = Input(shape=(None, num_decoder_tokens), name='decoder_inputs')
decoder_lstm = LSTM(units=HIDDEN_UNITS, return_state=True, return_sequences=True, name='decoder_lstm')
decoder_outputs, decoder_state_h, decoder_state_c = decoder_lstm(decoder_inputs,
                                                                 initial_state=encoder_states)
decoder_dense = Dense(units=num_decoder_tokens, activation='softmax', name='decoder_dense')
decoder_outputs = decoder_dense(decoder_outputs)

model = Model([context_inputs, question_inputs, decoder_inputs], decoder_outputs)

model.compile(loss='categorical_crossentropy', optimizer='rmsprop')

json = model.to_json()
open(MODEL_DIR + '/word-architecture.json', 'w').write(json)

Xtrain, Xtest, Ytrain, Ytest = train_test_split(data, data, test_size=0.2, random_state=42)

print(len(Xtrain))
print(len(Xtest))

train_gen = generate_batch(Xtrain)
test_gen = generate_batch(Xtest)

train_num_batches = len(Xtrain) // BATCH_SIZE
test_num_batches = len(Xtest) // BATCH_SIZE

checkpoint = ModelCheckpoint(filepath=WEIGHT_FILE_PATH, save_best_only=True)

model.fit_generator(generator=train_gen, steps_per_epoch=train_num_batches,
                    epochs=NUM_EPOCHS,
                    verbose=1, validation_data=test_gen, validation_steps=test_num_batches, callbacks=[checkpoint])

model.save_weights(WEIGHT_FILE_PATH)