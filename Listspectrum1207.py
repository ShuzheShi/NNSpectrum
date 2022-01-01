# designed for testing unique solution

import time
import math
import numpy as np
import matplotlib.pyplot as plt
import torch
# from torch._C import ThroughputBenchmark
import torch.optim as optim
import torch.nn as nn

# initialization
import ini
device = ini.initial("list")
from paras import args

# setting default rho and D
omegal = 500
omega_up = 20
domegai = omega_up/omegal
omegai = torch.linspace(domegai,omega_up,steps=omegal).to(device) #,requires_grad=True

taul = 25
tau_up = 20
dtaui = tau_up/taul
taui = torch.linspace(0.001 , tau_up - dtaui - 0.001,steps=taul).to(device)

input = torch.ones(1).to(device) # ,requires_grad=True

def chi2(pre,obs): 
    out = (obs - pre)**2 /(10**(- args.noise))**2 # chi2 with std
    out = out.sum()
    return out

def Dkl(p,q):
    dp = (max(p) - min(p))/len(p)
    p = p/(p*dp).sum()
    q = q/(q*dp).sum()
    out = np.log((p+1E-10)/(q+1E-10))
    out = p*out
    out = out*dp
    return out.sum()


def D(taui,omegai,rhoi):
    taui = taui.reshape(-1)
    omegai = omegai.reshape(1,-1)
    rhoi = rhoi.reshape(1,omegal)

    tauii = taui.reshape(len(taui),1).to(device)
    matri = torch.ones(len(taui),omegal).to(device)
    tauii = tauii* matri

    out = (omegai / (tauii**2 + omegai**2)/math.pi)*rhoi*domegai # /math.pi
    # #  out = torch.exp(-taui*omegai)*rhoi*domegai
    out = torch.sum(out,dim=1)
    return out

def Dp(taui,omegai,rhoi): # partial D(tau)
    taui = taui.reshape(-1)
    omegai = omegai.reshape(1,-1)
    rhoi = rhoi.reshape(1,omegal)

    tauii = taui.reshape(len(taui),1).to(device)
    tauii = tauii* torch.ones(len(taui),omegal).to(device)

    out = - (2* omegai * tauii / (tauii**2 + omegai**2) **2 /math.pi)*rhoi*domegai # /math.pi
    # #  out = torch.exp(-taui*omegai)*rhoi*domegai
    out = torch.sum(out,dim=1)
    return out

def init_weights(m):
    if type(m) == nn.Linear:
        torch.nn.init.xavier_normal_(m.weight)
        # m.bias.data.fill_(0.001)

class Net(nn.Module):
    def __init__(self, layers=None,):
        super(Net, self).__init__()

        self.layers = torch.nn.Sequential(
            nn.Linear(1,omegal,bias=False),nn.Softplus()
            )

    def forward(self, x):
        output = self.layers(x)
        return output


nnrho = Net()
nnrho.apply(init_weights)
nnrho = nnrho.to(device)

print(nnrho)

def count_parameters(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
print('parameters_count:',count_parameters(nnrho))


#############################################################################################
# import  mock  data #
######################
# data = np.loadtxt('correlatorsBW/D-{}.dat'.format(args.Index), delimiter='\t', unpack=True)
# taui = torch.from_numpy(data[0]).to(device)
# target = torch.from_numpy(data[1]).to(device)
truth = np.loadtxt('correlatorsBW/rho-{}.txt'.format(args.Index), delimiter=',', unpack=True)
data = np.loadtxt('correlatorsBW/Dtau-{}.txt'.format(args.Index), delimiter=',', unpack=True)
taui =  torch.from_numpy(data[0]).float().to(device)
target =  torch.from_numpy(data[1]).float().to(device)

taul = len(taui)
tau_up = max(taui)
dtaui = tau_up/taul

taui_p = taui[:-1] + dtaui/2
target_p = (target[1:] - target[:-1])/dtaui

if args.noise != 10:
    noise = np.loadtxt('correlatorsBW/noise-{}.txt'.format(args.noise), delimiter=',', unpack=True)
    target_noise = torch.from_numpy(noise).float().to(device) * target *taui/dtaui
    target += target_noise

out = nnrho(input)*omegai
out_old = out

t = time.time()


#############################################################################################
# warm up #
######################
checkpoint = 1
if checkpoint:
    nnrho = torch.load('listRho')
else:
    optimizer = optim.Adam(nnrho.parameters(), lr=args.lr, weight_decay = 0) # 1e-3
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=50000, gamma=0.1)
    l2_lambda = args.l2
    slambda = args.slambda
    nnrho.zero_grad()
    for epoch in range(args.epochs):  # loop over the dataset multiple times

        running_loss = 0.0
        for i  in range(25):
            # get the inputs; data is a list of [inputs, labels]
            # zero the parameter gradients
            optimizer.zero_grad()
            
            # forward + backward + optimize
            rhoi = (nnrho(input))*omegai
            outputs = D(taui,omegai,rhoi)
            # outputs_p = Dp(taui_p,omegai,rhoi)
            loss = chi2(outputs, target) #+  chi2(outputs_p, target_p)
            chis = loss.item()
            running_loss += loss.item()

            l2 = l2_lambda * sum([(p**2).sum() for p in nnrho.parameters()])
            loss+= l2/2

            # l_mem = l2_lambda * (rhoi - omegai -rhoi*torch.log(rhoi/omegai)).sum()
            # loss-= l_mem

            loss+= ((slambda*((rhoi[1:]-rhoi[:-1])**2).sum()))

            loss.backward()

            # for p in nnrho.parameters():
            #     p.data = p.data - args.lr*p.grad.data /rhoi.reshape(-1,1)
            # p.grad.zero_()

            optimizer.step()
            scheduler.step()

            if (i % 25 == 24)&(epoch % 50 == 49) :    # print every 20 epoches
                print('[%d, %5d] chi2: %.8e lr: %.5f loss: %8f' % 
                    (epoch + 1, i + 1, chis, optimizer.param_groups[0]['lr'],loss.item()))

        running_loss = 0.0

        if (epoch % 200 == 199) : 
            slambda *= 0.1
            l2_lambda = 1e-8

        if (epoch % 400 == 399) : 
            slambda = args.slambda
            l2_lambda = args.l2
    
    torch.save(nnrho, 'listRho')

#############################################################################################
# training #
############
l2_lambda = 1e-8/(10**(- args.noise))**2
optimizer = optim.Adam(nnrho.parameters(), lr=args.lr*0.1, weight_decay = 0) # 1e-3 AdamW
scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=50000, gamma=0.5)
nnrho.zero_grad()
for epoch in range(args.epochs*40):  # loop over the dataset multiple times
    running_loss = 0.0
    for i  in range(25):
        # get the inputs; data is a list of [inputs, labels]
        # zero the parameter gradients
        optimizer.zero_grad()
        
        # forward + backward + optimize
        rhoi = (nnrho(input))*omegai
        outputs = D(taui,omegai,rhoi)
        # outputs_p = Dp(taui_p,omegai,rhoi)
        loss = chi2(outputs, target) #+  chi2(outputs_p, target_p)
        chis = loss.item()

        l2 = l2_lambda * sum([(p**2).sum() for p in nnrho.parameters()])
        loss+= l2/2

        # l_mem = - l2_lambda * (rhoi - omegai -rhoi*torch.log(rhoi/omegai)).sum()
        # loss+= l_mem

        # loss+= ((slambda*((rhoi[1:]-rhoi[:-1])**2).sum()))

        running_loss += loss.item()
        
        loss.backward()

        # for p in nnrho.parameters():
        #     p.data = p.data - lr_manu*p.grad.data /rhoi.reshape(-1,1)
        # p.grad.zero_()
        # if (epoch % 1000 == 999) : 
        #     lr_manu /= 0.98

        optimizer.step()
        scheduler.step()

        if (i % 25 == 24)&(epoch % 50 == 49) :    # print every 20 epoches
            print('[%d, %5d] chi2: %.8e lr: %.10f lr: %8e' % 
                (epoch + 1 + args.epochs, i + 1, chis, optimizer.param_groups[0]['lr'], loss.item()))
    
    if loss< 10**(-args.noise * 2 - 1):
        print('Early stopping!' )
        break

    if epoch > args.maxiter and (running_loss/25 - loss.item())>=0:
        print('Early stopping!' )
        break

    running_loss = 0.0

print('Finished Training')
elapsed = time.time() - t
print('Cost Time = ',elapsed)
#############################################################################################
# plot figures and export #
############

out = (nnrho(input))*omegai
output = D(taui,omegai,out)

chis = chi2(output.cpu().detach().numpy(),target.cpu().detach().numpy())
dKL = Dkl(out.cpu().detach().numpy(),truth)
mse = ((out.cpu().detach().numpy()-truth)**2).sum()
print('Chi2(Dt) = ', chis)
print('D_KL(rho) = ', dKL)
print('MSE(rho) = ', mse)

from plotfig import plotfigure, saveresults
plotfigure(taui,omegai,truth,out,output,target)
saveresults("list",omegai,target,out,output)