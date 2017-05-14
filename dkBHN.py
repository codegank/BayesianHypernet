# -*- coding: utf-8 -*-
"""
Created on Fri May 12 17:46:38 2017

@author: Chin-Wei (and David Krueger :D)

TODO:
    logging
    double-check math
    launchable-ness (SLURM jobs)
    test-time MC (THEANO)


So far, it appears to be working, but not very well...
    so why not????
    do we need a better hypernet??
        at a glance, the architecture seems wrong...
            more layers, less scaling, ...?
            no random permutations (what's up with that??)


I'll need to read Real NVP, as well...



"""

from modules import LinearFlowLayer, IndexLayer, PermuteLayer
from modules import CoupledDenseLayer, CoupledConv1DLayer
from utils import log_stdnormal
from ops import load_mnist
import theano
import theano.tensor as T
from theano.tensor.shared_randomstreams import RandomStreams
srng = RandomStreams(seed=427)
floatX = theano.config.floatX

import lasagne
from lasagne import init
from lasagne import nonlinearities
from lasagne.layers import get_output
from lasagne.objectives import categorical_crossentropy as cc
import numpy as np

np.random.seed(427)


class stochasticDenseLayer(lasagne.layers.base.MergeLayer):
    
    def __init__(self, incomings, num_units, 
                 b=init.Constant(0.), nonlinearity=nonlinearities.rectify,
                 num_leading_axes=1, **kwargs):
        super(stochasticDenseLayer, self).__init__(incomings, **kwargs)
        self.nonlinearity = (nonlinearities.identity if nonlinearity is None
                             else nonlinearity)
        self.num_units = num_units
        
        if b is None:
            self.b = None
        else:
            self.b = self.add_param(b, (num_units,), name="b",
                                    regularizable=False)
    def get_output_shape_for(self,input_shapes):
        input_shape = input_shapes[0]
        weight_shape = input_shapes[1]
        return (input_shape[0], weight_shape[2])
        
    def get_output_for(self, inputs, **kwargs):
        """
        inputs[0].shape = (None, num_inputs)
        inputs[1].shape = (None/1, num_inputs, num_units)
        """
        input = inputs[0]
        W = inputs[1]
        activation = T.sum(input.dimshuffle(0,1,'x') * W, axis = 1)
        if self.b is not None:
            activation = activation + self.b
        return self.nonlinearity(activation)



# TODO: use init_W instead of std!
# TODO: prior?

if 1:
#def main():
    """
    MNIST example
    """
    
    import argparse
    
    parser = argparse.ArgumentParser()
    # different noise for each datapoint (vs. each minibatch)
    parser.add_argument('--bs',default=32,type=int)  
    parser.add_argument('--coupling',default='none',type=str, choices=['conv', 'dense', 'none'])  
    parser.add_argument('--epochs',default=100,type=int)  
    parser.add_argument('--fix_sigma',default=0,type=int)  
    parser.add_argument('--init_lr',default=.1,type=float)  
    parser.add_argument('--opt',default='momentum',type=str)  
    parser.add_argument('--perdatapoint',default=0,type=bool)    
    parser.add_argument('--primary_layers',default=1,type=int)    
    parser.add_argument('--primary_hids',default=10,type=int)    
    parser.add_argument('--std',default=1.,type=bool)    
    # num_ex
    parser.add_argument('--size',default=10000,type=int)  
    args = parser.parse_args()
    locals().update(args.__dict__)
    print args

    perdatapoint = args.perdatapoint
    coupling = args.coupling
    size = max(10,min(50000,args.size))
    print "size",size
    # these seem large!
    clip_grad = 100
    max_norm = 1000
    
    # load dataset
    filename = '/data/lisa/data/mnist.pkl.gz'
    train_x, train_y, valid_x, valid_y, test_x, test_y = load_mnist(filename)
    
    
    input_var = T.matrix('input_var')
    target_var = T.matrix('target_var')
    dataset_size = T.scalar('dataset_size')
    lr = T.scalar('lr') 
    
    # 784 -> 10 -> 10
    weight_shapes = []
    if primary_layers == 0:
        weight_shapes.append((784, 10))
    else:
        weight_shapes.append((784, primary_hids))
        for _ in primary_layers:
            weight_shapes.append((primary_hids, primary_hids))
        weight_shapes.append((primary_hids, 10))
    
    num_params = sum(np.prod(ws) for ws in weight_shapes)
    if perdatapoint:
        wd1 = input_var.shape[0]
    else:
        wd1 = 1

    # stochastic hypernet    
    ep = srng.normal(size=(wd1,num_params), std=std, dtype=floatX)
    logdets_layers = []
    h_layer = lasagne.layers.InputLayer([None,num_params])
    
    layer_temp = LinearFlowLayer(h_layer)
    h_layer = IndexLayer(layer_temp,0)
    logdets_layers.append(IndexLayer(layer_temp,1))
    
    if coupling == 'conv':
        if fix_sigma: assert False # not implemented
        layer_temp = CoupledConv1DLayer(h_layer,16,5)
        h_layer = IndexLayer(layer_temp,0)
        logdets_layers.append(IndexLayer(layer_temp,1))
        
        h_layer = PermuteLayer(h_layer,num_params)
        
        layer_temp = CoupledConv1DLayer(h_layer,16,5)
        h_layer = IndexLayer(layer_temp,0)
        logdets_layers.append(IndexLayer(layer_temp,1))
    
    elif coupling == 'dense':
        layer_temp = CoupledDenseLayer(h_layer, num_params, fix_sigma=fix_sigma)
        h_layer = IndexLayer(layer_temp,0)
        logdets_layers.append(IndexLayer(layer_temp,1))
        
        h_layer = PermuteLayer(h_layer,num_params)
        
        layer_temp = CoupledDenseLayer(h_layer, num_params, fix_sigma=fix_sigma)
        h_layer = IndexLayer(layer_temp,0)
        logdets_layers.append(IndexLayer(layer_temp,1))
    
    # pseudo-params
    weights = lasagne.layers.get_output(h_layer,ep)
    
    # primary net
    t = np.cast['int32'](0)
    layer = lasagne.layers.InputLayer([None,784])
    inputs = {layer:input_var}
    for ws in weight_shapes: # TODO: perdatapoint will break here!
        num_param = np.prod(ws)
        #print t, t+num_param
        w_layer = lasagne.layers.InputLayer((None,)+ws)
        weight = weights[:,t:t+num_param].reshape((wd1,)+ws)
        inputs[w_layer] = weight
        layer = stochasticDenseLayer([layer,w_layer],ws[1])
        t += num_param
        
    layer.nonlinearity = nonlinearities.softmax
    y = get_output(layer,inputs)
    #y = T.clip(y, 0.00001, 0.99999) # stability 

    
    # loss terms
    # TODO: monitor separately
    logdets = sum([get_output(logdet,ep) for logdet in logdets_layers])
    # FIXME: are we using *different* epsilons when we should be using the same ones???
    logqw = - (0.5*(ep**2).sum(1) + 0.5*T.log(2*np.pi)*num_params + logdets)
    logpw = log_stdnormal(weights).sum(1)
    kl = (logqw - logpw).mean()
    logpyx = - cc(y,target_var).mean()
    # FIXME: shouldn't this be the batch_size??
    loss = - (logpyx - kl/T.cast(dataset_size,floatX))
    outputs = [loss, logpyx, logdets]
    
    params = lasagne.layers.get_all_params([h_layer,layer])
    grads = T.grad(loss, params)
    # double clipping??
    mgrads = lasagne.updates.total_norm_constraint(grads,
                                                   max_norm=max_norm)
    cgrads = [T.clip(g, -clip_grad, clip_grad) for g in mgrads]
    if opt == 'adam':
        updates = lasagne.updates.adam(cgrads, params, learning_rate=lr)
    elif opt == 'momentum':
        updates = lasagne.updates.nesterov_momentum(cgrads, params, learning_rate=lr)
                                            
    
    train = theano.function([input_var,target_var,dataset_size,lr],
                            outputs,
                            updates=updates)
    output_probs = theano.function([input_var],y)
    predict = theano.function([input_var],y.argmax(1))
    
    ###########################
    # TRAIN MODEL
    #def train_model(train_func,predict_func,X,Y,Xt,Yt,bs=20):
    #records = train_model(train,predict,
     #                     train_x[:size],train_y[:size],
     #                     valid_x,valid_y)
    X,Y = train_x[:size], train_y[:size]
    Xt,Yt = valid_x[:size], valid_y[:size]
    print 'trainset X.shape:{}, Y.shape:{}'.format(X.shape,Y.shape)
    N = X.shape[0]    
    records=list()
    
    t = 0
    for e in range(epochs):

        current_lr = init_lr #* 10**(-e/float(epochs-1))                    
        for i in range(N/bs):
            x = X[i*bs:(i+1)*bs]
            y = Y[i*bs:(i+1)*bs]
            
            outputs = train(x,y,N,current_lr)
            
            if t%100==0:
                print 'epoch: {} {}, loss:{}'.format(e,t,outputs)
                acc = (predict(Xt)==Yt.argmax(1)).mean()
                print '\tacc: {}'.format(acc)
            t+=1
            
        records.append(loss)
    # END TRAIN MODEL
    ###########################


    # TODO: add evaluation!!!


    
    #from utils import fplot
    for pp in params:
        pass#fplot(pp.eval())
    
    #TODO: 
    g=theano.function([input_var,target_var],T.grad(-logpyx,params[0]))
    sg = g(train_x[:2],train_y[:2])[:7840]#  ----> all zeros if use > 2 layers!


