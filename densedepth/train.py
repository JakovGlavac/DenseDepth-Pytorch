import time  
import argparse as arg 
import datetime

import torch  
import torch.nn as nn  
import torch.nn.utils as utils
import torch.optim as optim
import torchvision.utils as vision_utils  
from tensorboardX import SummaryWriter

from model import DenseDepth
from losses import ssim as ssim_criterion
from losses import depth_loss as gradient_criterion
from data import getTrainingTestingData
from utils import AverageMeter, DepthNorm, colorize, load_from_checkpoint


def main():

    # CLI arguments  
    parser = arg.ArgumentParser(description='Training method for\t'
                                'High Quality Monocular Depth Estimation via Transfer Learning')
    parser.add_argument("--epochs", "-e", default=20, type=int, help="total number of epochs to run training for")
    parser.add_argument("--lr", "-l", default=0.0001, type=float, help="initial learning rate")
    parser.add_argument("--batch", "-b", default=8, type=int, help="Batch size")
    parser.add_argument("--checkpoint", "-c", default="", type=str, help="path to last saved checkpoint to resume training from")
    parser.add_argument("--resume_epoch", "-r", default=-1, type=int, help="epoch to resume training from")
    parser.add_argument("--device", "-d", default="cuda", type=str, help="device to run training on. Use CUDA")
    parser.add_argument("--enc_pretrain", "-p", default=True, type=bool, help="Use pretrained encoder")
    parser.add_argument("--data", default="data/nyu_data.zip", type=str, help="path to dataset")
    parser.add_argument("--theta", "-t", default=0.1, type=float, help="coeff for L1 (depth) Loss")

    args = parser.parse_args()

    # Load data
    print("Loading Data ...")
    trainloader, testloader = getTrainingTestingData(args.data, batch_size=args.batch)
    print("Datalaoders ready ...")
    num_trainloader = len(trainloader)
    num_testloader = len(testloader)

    # initialize the model with pretrained ImageNet weights    
    print("Model init ...")
    model = DenseDepth(encoder_pretrained=args.enc_pretrain)
    print("Model initialized ...")

    # Training utils  
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    batch_size = args.batch
    model_prefix = "densedepth_"
    device = args.device
    theta = args.theta
    save_count = 0
    epoch_loss = []
    batch_loss = []
    sum_loss = 0

    # loading from checkpoint if provided 
    if len(args.checkpoint) > 0:
        model, optimizer, args.epochs = load_from_checkpoint(args.checkpoint, model, optimizer, args.epochs)

    model = model.to(device)

    # Logging
    writer = SummaryWriter(comment="{}-learning_rate:{}-epoch:{}-batch_size:{}".format(
        model_prefix, args.lr, args.epochs, args.batch
    ))
    
    # Loss functions 
    l1_criterion = nn.L1Loss()

    # Starting training 
    print("Starting training ... ")
    model.train() 
    for epoch in range(args.epochs):

        batch_time = AverageMeter() 
        loss_meter = AverageMeter() 

        epoch_start = time.time()
        end = time.time()

        for idx, batch in enumerate(trainloader):

            optimizer.zero_grad() 

            image_x = torch.Tensor(batch["image"]).to(device)
            depth_y = torch.Tensor(batch["depth"]).to(device=device, non_blocking=True)

            normalized_depth_y = DepthNorm(depth_y)

            preds = model(image_x)

            # calculating the losses 
            l1_loss = l1_criterion(preds, normalized_depth_y)
            
            ssim_loss = torch.clamp(
                (1-ssim_criterion(preds, normalized_depth_y, 1000.0/10.0))*0.5, 
                min=0, 
                max=1
            )

            gradient_loss = gradient_criterion(normalized_depth_y, preds, device=device)

            net_loss = (1.0 * ssim_loss) + (1.0 * torch.mean(gradient_loss)) + (theta * torch.mean(l1_loss))

            loss_meter.update(net_loss.data.item(), image_x.size(0))
            net_loss.backward()
            optimizer.step()

            # Time metrics 
            batch_time.update(time.time() - end)
            end = time.time()
            eta = str(datetime.timedelta(seconds=int(batch_time.val*(num_trainloader-idx))))

            # Logging  
            num_iters = epoch * num_trainloader + idx  
            if idx % 5 == 0 :
                print(
                    "Epoch: #{0} Batch: {1}/{2}\t"
                    "Time (current/total) {batch_time.val:.3f}/{batch_time.sum:.3f}\t"
                    "eta {eta}\t"
                    "LOSS (current/average) {loss.val:.4f}/{loss.avg:.4f}\t"
                    .format(epoch, idx, num_trainloader, batch_time=batch_time, eta=eta, loss=loss_meter)
                )

                writer.add_scalar("Train/Loss", loss_meter.val, num_iters)

            #if idx % 300 == 0:
                #LogProgress(model, writer, testloader, num_iters, device)
            #print(torch.cuda.memory_allocated()/1e+9)
            del image_x
            del depth_y
            del preds          
           #print(torch.cuda.memory_allocated()/1e+9)
        #LogProgress(model, writer, testloader, num_iters, device)
        
        if epoch % 1 == 0:
            print(
                "----------------------------------\t",
                "Epoch: #{}, Avg. Net Loss: {4f}\t",
                "----------------------------------"
                .format(
                    epoch, loss_meter.avg
                )
            )
            torch.save({
                "epoch": epoch, 
                "model_state_dict": model.cpu().state_dict(),
                "optim_state_dict":  optimizer.cpu().state_dict(),
                "loss": loss_meter.avg
            }, "ckpt_tmp.pth") 

        if epoch == ((args.epochs % 5) + save_count) :

            torch.save({
                "epoch": epoch, 
                "model_state_dict": model.cpu().state_dict(),
                "optim_state_dict":  optimizer.cpu().state_dict(),
                "loss": loss_meter.avg
            }, "ckpt_{}_{}.pth".format(epoch, int(loss_meter.avg*100)))

            save_count = (args.epochs % 5) + save_count





def LogProgress(model, writer, test_loader, epoch, device):
    
    """ To record intermediate results of training""" 

    model.eval() 
    sequential = test_loader
    sample_batched = next(iter(sequential))
    
    image = torch.Tensor(sample_batched["image"]).to(device)
    depth = torch.Tensor(sample_batched["depth"]).to(device
    
    if epoch == 0:
        writer.add_image("Train.1.Image", vision_utils.make_grid(image.data, nrow=6, normalize=True), epoch)
    if epoch == 0:
        writer.add_image("Train.2.Image", colorize(vision_utils.make_grid(depth.data, nrow=6, normalize=False)), epoch)
    
    output = DepthNorm(model(image))

    writer.add_image("Train.3.Ours", colorize(vision_utils.make_grid(output.data, nrow=6, normalize=False)), epoch)
    writer.add_image("Train.4.Diff", colorize(vision_utils.make_grid(torch.abs(output-depth).data, nrow=6, normalize=False)), epoch)
    
    del image
    del depth
    del output








if __name__ == "__main__":
    main()