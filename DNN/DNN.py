'''

DNN.py

Trains a Keras deep neural network on the DAMPE electron-proton separation problem.

- Runs five times, each time on a random set of parameters
- DNN parameters are chosen randomly with getRandomParams(), which contains lists of possible parameters. Set of parameters saved in ./models
- DNN model is created dynamically from getModel.py
- Model is saved after each epoch in ./models
- Results are saved in ./results/*ID*/   where ID is a hash number corresponding to the set of parameters
- Main results are printed to screen:  Precision (purity) and Recall (completeness)



'''



import numpy as np
import time
import cPickle as pickle
import sys
import os
import random
import hashlib

from keras.models import Sequential
from keras.layers.core import Dense, Dropout
from keras.callbacks import ModelCheckpoint, EarlyStopping, Callback, LearningRateScheduler, ReduceLROnPlateau
from keras.constraints import maxnorm
from keras.layers.advanced_activations import PReLU, ELU, LeakyReLU

from scipy.stats import randint as sp_randint

from sklearn.ensemble import GradientBoostingClassifier
from sklearn.externals import joblib
from sklearn.metrics import roc_curve, roc_auc_score, precision_score, average_precision_score, precision_recall_curve, recall_score
from sklearn.metrics import f1_score
from sklearn.model_selection import RandomizedSearchCV, GridSearchCV

from keras.wrappers.scikit_learn import KerasClassifier

import getModel

##############################################

# Possible parameters

def ParamsID(a):
	'''
	Using hash function to build an unique identifier for each dictionary
	'''
	ID = 1
	for x in ['acti_out','init','optimizer']:
		ID = ID + int(hashlib.sha256(a[x].encode('utf-8')).hexdigest(), 16)
	ID = ID + int(hashlib.sha256(str(a['activation'] + 'b').encode('utf-8')).hexdigest(), 16) 
	ID = ID + int(hashlib.sha256(str(a['dropout']).encode('utf-8')).hexdigest(), 16) 
	ID = ID + int(hashlib.sha256(str(len(a['architecture'])).encode('utf-8')).hexdigest(), 16)
	for y in a['architecture']:
		ID = ID + int(hashlib.sha256(str(y).encode('utf-8')).hexdigest(), 16) 
	ID = ID + int(a['batchnorm'])
	return (ID % 10**10)

def getRandomParams():
	'''
	Returns a dictionary containing all the parameters to train the Keras DNN. Is then fed to getModel::getModel()
	'''
	p_dropout = [0.,0.1,0.2,0.5]
	p_batchnorm = [True, True, False]			# Repetition of values to increase probability
	p_activation = ['relu','relu','relu','sigmoid','softplus','elu','elu']
	#~ p_activation = ['relu','relu','relu','sigmoid','softplus','elu','elu',PRelu(),PRelu(),ELU(),LeakyReLU()]	 
	p_acti_out = ['sigmoid','sigmoid','sigmoid','relu']
	p_init = ['uniform','glorot_uniform','glorot_normal','lecun_uniform','he_uniform','he_normal']
	p_loss = ['binary_crossentropy']
	p_optimizer = ['adagrad','adadelta','adam','adamax','nadam','sgd']
	p_metric = [['binary_accuracy']]
	p_architecture = [ 	[50,20,1],
						[50,25,12,1],
						[60,20,1],
						[60,30,15,1],
						[100,50,25,1],
						[100,100,100,1],
						[200,100,50,1],
						[200,100,50,25,1],
						[300,300,300,1],
						[300,150,75,1],
						[300,200,100,50,1] ]
						
	mydic = {}
	mydic['architecture'] = random.choice(p_architecture)
	mydic['dropout'] = random.choice(p_dropout)
	mydic['batchnorm'] = random.choice(p_batchnorm)
	mydic['activation'] = random.choice(p_activation)
	mydic['acti_out'] = random.choice(p_acti_out)
	mydic['init'] = random.choice(p_init)
	mydic['loss'] = random.choice(p_loss)
	mydic['optimizer'] = random.choice(p_optimizer)
	mydic['metrics'] = random.choice(p_metric)
	
	return mydic

def XY_split(fname):
	arr = np.load(fname)
	X = arr[:,0:-2]				### Last two columns are timestamp and particle id
	Y = arr[:,-1]
	return X,Y
def load_training(fname='dataset_train.npy'): return XY_split(fname)
def load_validation(fname='dataset_validate.npy'): return XY_split(fname)
def load_test(fname='dataset_test.npy'): return XY_split(fname)

def _normalise(arr):
	for i in xrange(arr.shape[1]):
		if np.all(arr[:,i] > 0) :
			arr[:,i] = (arr[:,i] - np.mean(arr[:,i]) + 1.) / np.std(arr[:,i])		# Mean = 1 if all values are strictly positive (from paper)
		else:
			arr[:,i] = (arr[:,i] - np.mean(arr[:,i])) / np.std(arr[:,i])	
	return arr

def save_history(hist, hist_filename):
	import pandas as pd

	df_history = pd.DataFrame(np.asarray(hist.history.get("loss")), columns=['loss'])
	df_history['acc'] = pd.Series(np.asarray(hist.history.get("acc")), index=df_history.index)
	df_history['val_loss'] = pd.Series(np.asarray(hist.history.get("val_loss")), index=df_history.index)
	df_history['val_acc'] = pd.Series(np.asarray(hist.history.get("val_acc")), index=df_history.index)
	df_history.to_hdf(hist_filename, key='history', mode='w')	
	
def run():
	
	t0 = time.time()
	
	X_train, Y_train = load_training()
	X_val, Y_val = load_validation()
	
	X_train = _normalise(X_train)
	X_val = _normalise(X_val)
	
	while True:
		params = getRandomParams()
		ID = ParamsID(params)										# Get an unique ID associated to the parameters
		if not os.path.isfile('results/' + str(ID) + '/purity_completeness.txt'):		# Check if set of params has already been tested. Don't write file yet because what's below can get interrupted
			break
	
	
	model = getModel.get_model(params,X_train.shape[1])
	
	if not os.path.isdir('models'): os.mkdir('models')
	
	
	with open('models/params_' + str(ID) + '.pick','w') as f:	# Save the parameters into a file determined by unique ID
		pickle.dump(params,f)
		
	chck = ModelCheckpoint("models/weights_"+str(ID)+"__{epoch:02d}-{val_loss:.2f}-{val_acc:.2f}.hdf5")
	earl = EarlyStopping(monitor='loss',min_delta=0.0001,patience=5)			# Alternative: train epoch per epoch, evaluate something at every epoch.
	rdlronplt = ReduceLROnPlateau(monitor='loss',patience=4,min_lr=0.001)
	callbacks = [chck,earl,rdlronplt]
	
	history = model.fit(X_train,Y_train,batch_size=200,epochs=200,verbose=0,callbacks=callbacks,validation_data=(X_val,Y_val))
	
	predictions_binary = model.predict(X_val)			# Array of 0 and 1
	predictions_proba = model.predict_proba(X_val)		# Array of numbers [0,1]
	
	purity = precision_score(Y_val,predictions_binary)			# Precision:  true positive / (true + false positive). Purity (how many good events in my prediction?)
	completeness = recall_score(Y_val,predictions_binary)		# Recall: true positive / (true positive + false negative). Completeness (how many good events did I find?)
	F1score = f1_score(Y_val,predictions_binary)				# Average of precision and recall
	
	l_precision, l_recall, l_thresholds = precision_recall_curve(Y_val,predictions_proba)
	
	
	# 1 - precision = 1 - (TP/(TP + FP)) = (TP + FP)/(TP + FP) - (TP / (TP+FP)) = FP/(TP+FP) = FPR
	
	prec_95 = None
	recall_95 = None
	for i in xrange(len(l_precision)):
		if l_precision[i] > 0.95 :
			if prec_95 is None:
				prec_95 = l_precision[i]
				recall_95 = l_recall[i]
			else:
				if l_precision[i] < prec_95:
					prec_95 = l_precision[i]
					recall_95 = l_recall[i]
					
	print "Precision: ", prec_95
	print "Recall: ", recall_95
	print "Iteration run time: ", time.strftime('%H:%M:%S', time.gmtime(time.time() - t0))	
	
	if not os.path.isdir('results'): os.mkdir('results')
	if not os.path.isdir('results/' + str(ID)) : os.mkdir('results/' + str(ID))
	with open('results/' + str(ID) + '/results.pick','w') as f:
		pickle.dump([l_precision,l_recall,l_thresholds],f)
	numpy.save('results/' + str(ID) + '/predictions.npy',predictions_proba)
	numpy.save('results/' + str(ID) + '/Y_Val.npy',Y_val)
	with open('results/' + str(ID) + '/purity_completeness.txt','w') as g:
		g.write("Precision: "+str(prec_95)+'\n')
		g.write("Recall: "+str(recall_95)+'\n')
	save_history(history,'results/'+str(ID)+'/history.hdf')
	
		
		
	
if __name__ == '__main__' :
	
	for x in xrange(5):
		print '------------ ', x, ' ----------------'
		run()

