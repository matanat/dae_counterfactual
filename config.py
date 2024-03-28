from model.unet import ScaleAt
from model.latentnet import *
from diffusion.resample import UniformSampler
from diffusion.diffusion import space_timesteps
from typing import Tuple

from torch.utils.data import DataLoader

from config_base import BaseConfig
from dataset import *
from diffusion import *
from diffusion.base import GenerativeType, LossType, ModelMeanType, ModelVarType, get_named_beta_schedule
from model import *
from choices import *
from multiprocessing import get_context
import os
from dataset_util import *
from torch.utils.data.distributed import DistributedSampler

from medmnist.dataset import RetinaMNIST
from torchvision.transforms import ToTensor
import monai.transforms as T
from monai.apps import DecathlonDataset
import monai.data as data

def create_spider_files(split="training"):
    meta = pd.read_csv("/DATA/NAS/datasets_source/mri_spine/dataset-spider/overview.csv")
    labels = pd.read_csv("/DATA/NAS/datasets_source/mri_spine/dataset-spider/radiological_gradings.csv")

    meta_train = meta[(meta.subset == split) & (meta.new_file_name.str.endswith("t2"))]

    img_path = "/DATA/NAS/datasets_source/mri_spine/dataset-spider/images/"
    mask_path = "/DATA/NAS/datasets_source/mri_spine/dataset-spider/masks/"

    files = list()
    for f in list(meta_train.new_file_name):
        rec = dict()
        rec['image'] = img_path + f + ".mha"
        rec['mask'] = mask_path + f + ".mha"
        rec['patient'] = int(f.split('_')[0])

        num_vertebrae = meta_train[meta_train.new_file_name == f]['num_vertebrae'].item()
        for v in range(1, num_vertebrae + 1):
            rec['ivd_label'] = v
            match = labels[(labels['Patient'] == rec['patient']) & (labels['IVD label']== v)]
            if len(match['Pfirrman grade']) != 1:
                print("Missing grade, skipping IVD")
                continue
            rec['pfirrman_grade'] = match['Pfirrman grade'].item() - 1
            files.append(rec.copy())

    # something wrong with this
    files = [f for f in files if not (f['patient'] == 256 and f['ivd_label']) == 8]
    
    return files

data_paths = {
    'ffhqlmdb256':
    os.path.expanduser('datasets/ffhq256.lmdb'),
    # used for training a classifier
    'celeba':
    os.path.expanduser('datasets/celeba'),
    # used for training DPM models
    'celebalmdb':
    os.path.expanduser('datasets/celeba.lmdb'),
    'celebahq':
    os.path.expanduser('datasets/celebahq256.lmdb'),
    'horse256':
    os.path.expanduser('datasets/horse256.lmdb'),
    'bedroom256':
    os.path.expanduser('datasets/bedroom256.lmdb'),
    'celeba_anno':
    os.path.expanduser('datasets/celeba_anno/list_attr_celeba.txt'),
    'celebahq_anno':
    os.path.expanduser(
        'datasets/celeba_anno/CelebAMask-HQ-attribute-anno.txt'),
    'celeba_relight':
    os.path.expanduser('datasets/celeba_hq_light/celeba_light.txt'),
}


@dataclass
class PretrainConfig(BaseConfig):
    name: str
    path: str


@dataclass
class TrainConfig(BaseConfig):
    # random seed
    seed: int = 0
    train_mode: TrainMode = TrainMode.diffusion
    train_cond0_prob: float = 0
    train_pred_xstart_detach: bool = True
    train_interpolate_prob: float = 0
    train_interpolate_img: bool = False
    manipulate_mode: ManipulateMode = ManipulateMode.celebahq_all
    manipulate_cls: str = None
    manipulate_shots: int = None
    manipulate_loss: ManipulateLossType = ManipulateLossType.bce
    manipulate_znormalize: bool = False
    manipulate_seed: int = 0
    accum_batches: int = 1
    autoenc_mid_attn: bool = True
    batch_size: int = 16
    batch_size_eval: int = None
    beatgans_gen_type: GenerativeType = GenerativeType.ddim
    beatgans_loss_type: LossType = LossType.mse
    beatgans_model_mean_type: ModelMeanType = ModelMeanType.eps
    beatgans_model_var_type: ModelVarType = ModelVarType.fixed_large
    beatgans_rescale_timesteps: bool = False
    latent_infer_path: str = None
    latent_znormalize: bool = False
    latent_gen_type: GenerativeType = GenerativeType.ddim
    latent_loss_type: LossType = LossType.mse
    latent_model_mean_type: ModelMeanType = ModelMeanType.eps
    latent_model_var_type: ModelVarType = ModelVarType.fixed_large
    latent_rescale_timesteps: bool = False
    latent_T_eval: int = 1_000
    latent_clip_sample: bool = False
    latent_beta_scheduler: str = 'linear'
    beta_scheduler: str = 'linear'
    data_name: str = ''
    data_val_name: str = None
    diffusion_type: str = None
    dropout: float = 0.1
    ema_decay: float = 0.9999
    eval_num_images: int = 5_000
    eval_every_samples: int = 200_000
    eval_ema_every_samples: int = 200_000
    fid_use_torch: bool = True
    fp16: bool = False
    grad_clip: float = 1
    img_size: int = 64
    lr: float = 0.0001
    optimizer: OptimizerType = OptimizerType.adam
    weight_decay: float = 0
    model_conf: ModelConfig = None
    model_name: ModelName = None
    model_type: ModelType = None
    net_attn: Tuple[int] = None
    net_beatgans_attn_head: int = 1
    # not necessarily the same as the the number of style channels
    net_beatgans_embed_channels: int = 512
    net_resblock_updown: bool = True
    net_enc_use_time: bool = False
    net_enc_pool: str = 'adaptivenonzero'
    net_beatgans_gradient_checkpoint: bool = False
    net_beatgans_resnet_two_cond: bool = False
    net_beatgans_resnet_use_zero_module: bool = True
    net_beatgans_resnet_scale_at: ScaleAt = ScaleAt.after_norm
    net_beatgans_resnet_cond_channels: int = None
    net_ch_mult: Tuple[int] = None
    net_ch: int = 64
    net_enc_attn: Tuple[int] = None
    net_enc_k: int = None
    # number of resblocks for the encoder (half-unet)
    net_enc_num_res_blocks: int = 2
    net_enc_channel_mult: Tuple[int] = None
    net_enc_grad_checkpoint: bool = False
    net_autoenc_stochastic: bool = False
    net_latent_activation: Activation = Activation.silu
    net_latent_channel_mult: Tuple[int] = (1, 2, 4)
    net_latent_condition_bias: float = 0
    net_latent_dropout: float = 0
    net_latent_layers: int = None
    net_latent_net_last_act: Activation = Activation.none
    net_latent_net_type: LatentNetType = LatentNetType.none
    net_latent_num_hid_channels: int = 1024
    net_latent_num_time_layers: int = 2
    net_latent_skip_layers: Tuple[int] = None
    net_latent_time_emb_channels: int = 64
    net_latent_use_norm: bool = False
    net_latent_time_last_act: bool = False
    net_num_res_blocks: int = 2
    # number of resblocks for the UNET
    net_num_input_res_blocks: int = None
    net_enc_num_cls: int = None
    num_workers: int = 4
    parallel: bool = False
    postfix: str = ''
    sample_size: int = 64
    sample_every_samples: int = 20_000
    save_every_samples: int = 100_000
    style_ch: int = 512
    T_eval: int = 1_000
    T_sampler: str = 'uniform'
    T: int = 1_000
    total_samples: int = 10_000_000
    warmup: int = 0
    pretrain: PretrainConfig = None
    continue_from: PretrainConfig = None
    eval_programs: Tuple[str] = None
    # if present load the checkpoint from this path instead
    eval_path: str = None
    base_dir: str = 'checkpoints'
    use_cache_dataset: bool = False
    data_cache_dir: str = os.path.expanduser('~/cache')
    work_cache_dir: str = os.path.expanduser('~/mycache')
    # to be overridden
    name: str = ''
    in_channels: int = 3
    out_channels: int = 3

    dataset_img_key = 'img'

    def __post_init__(self):
        self.batch_size_eval = self.batch_size_eval or self.batch_size
        self.data_val_name = self.data_val_name or self.data_name

    def scale_up_gpus(self, num_gpus, num_nodes=1):
        self.eval_ema_every_samples *= num_gpus * num_nodes
        self.eval_every_samples *= num_gpus * num_nodes
        self.sample_every_samples *= num_gpus * num_nodes
        self.batch_size *= num_gpus * num_nodes
        self.batch_size_eval *= num_gpus * num_nodes
        return self

    @property
    def batch_size_effective(self):
        return self.batch_size * self.accum_batches

    @property
    def fid_cache(self):
        # we try to use the local dirs to reduce the load over network drives
        # hopefully, this would reduce the disconnection problems with sshfs
        return f'{self.work_cache_dir}/eval_images/{self.data_name}_size{self.img_size}_{self.eval_num_images}'

    @property
    def data_path(self):
        # may use the cache dir
        path = data_paths[self.data_name]
        if self.use_cache_dataset and path is not None:
            path = use_cached_dataset_path(
                path, f'{self.data_cache_dir}/{self.data_name}')
        return path

    @property
    def logdir(self):
        return f'{self.base_dir}/{self.name}'

    @property
    def generate_dir(self):
        # we try to use the local dirs to reduce the load over network drives
        # hopefully, this would reduce the disconnection problems with sshfs
        return f'{self.work_cache_dir}/gen_images/{self.name}'

    def _make_diffusion_conf(self, T=None):
        if self.diffusion_type == 'beatgans':
            # can use T < self.T for evaluation
            # follows the guided-diffusion repo conventions
            # t's are evenly spaced
            if self.beatgans_gen_type == GenerativeType.ddpm:
                section_counts = [T]
            elif self.beatgans_gen_type == GenerativeType.ddim:
                section_counts = f'ddim{T}'
            else:
                raise NotImplementedError()

            return SpacedDiffusionBeatGansConfig(
                gen_type=self.beatgans_gen_type,
                model_type=self.model_type,
                betas=get_named_beta_schedule(self.beta_scheduler, self.T),
                model_mean_type=self.beatgans_model_mean_type,
                model_var_type=self.beatgans_model_var_type,
                loss_type=self.beatgans_loss_type,
                rescale_timesteps=self.beatgans_rescale_timesteps,
                use_timesteps=space_timesteps(num_timesteps=self.T,
                                              section_counts=section_counts),
                fp16=self.fp16,
            )
        else:
            raise NotImplementedError()

    def _make_latent_diffusion_conf(self, T=None):
        # can use T < self.T for evaluation
        # follows the guided-diffusion repo conventions
        # t's are evenly spaced
        if self.latent_gen_type == GenerativeType.ddpm:
            section_counts = [T]
        elif self.latent_gen_type == GenerativeType.ddim:
            section_counts = f'ddim{T}'
        else:
            raise NotImplementedError()

        return SpacedDiffusionBeatGansConfig(
            train_pred_xstart_detach=self.train_pred_xstart_detach,
            gen_type=self.latent_gen_type,
            # latent's model is always ddpm
            model_type=ModelType.ddpm,
            # latent shares the beta scheduler and full T
            betas=get_named_beta_schedule(self.latent_beta_scheduler, self.T),
            model_mean_type=self.latent_model_mean_type,
            model_var_type=self.latent_model_var_type,
            loss_type=self.latent_loss_type,
            rescale_timesteps=self.latent_rescale_timesteps,
            use_timesteps=space_timesteps(num_timesteps=self.T,
                                          section_counts=section_counts),
            fp16=self.fp16,
        )

    @property
    def model_out_channels(self):
        return self.out_channels

    def make_T_sampler(self):
        if self.T_sampler == 'uniform':
            return UniformSampler(self.T)
        else:
            raise NotImplementedError()

    def make_diffusion_conf(self):
        return self._make_diffusion_conf(self.T)

    def make_eval_diffusion_conf(self):
        return self._make_diffusion_conf(T=self.T_eval)

    def make_latent_diffusion_conf(self):
        return self._make_latent_diffusion_conf(T=self.T)

    def make_latent_eval_diffusion_conf(self):
        # latent can have different eval T
        return self._make_latent_diffusion_conf(T=self.latent_T_eval)

    def make_dataset(self, path=None, **kwargs):
        if self.data_name == 'ffhqlmdb256':
            return FFHQlmdb(path=path or self.data_path,
                            image_size=self.img_size,
                            **kwargs)
        elif self.data_name == 'horse256':
            return Horse_lmdb(path=path or self.data_path,
                              image_size=self.img_size,
                              **kwargs)
        elif self.data_name == 'bedroom256':
            return Horse_lmdb(path=path or self.data_path,
                              image_size=self.img_size,
                              **kwargs)
        elif self.data_name == 'celebalmdb':
            # always use d2c crop
            return CelebAlmdb(path=path or self.data_path,
                              image_size=self.img_size,
                              original_resolution=None,
                              crop_d2c=True,
                              **kwargs)
        elif self.data_name == "retina128":
            train_transform = T.Compose([
                ToTensor(),
                T.RandRotate(range_x=np.pi / 12, prob=0.5, keep_size=True),
                T.RandFlip(spatial_axis=[-1, -2], prob=0.5),
                T.RandGridDistortion(prob=0.5),
                T.RandZoom(min_zoom=0.9, max_zoom=1.1, prob=0.5),
                T.ScaleIntensity(),
            ])
            return RetinaMNIST(split="train", 
                               transform=train_transform, 
                               download=True, 
                               as_rgb=True, 
                               size=self.img_size, 
                               root="/DATA/NAS/datasets_source/other")
        elif self.data_name == "brats64":
            channel = 0  # 0 = Flair
            train_transforms = T.Compose(
                [
                    T.LoadImaged(keys=["image", "label"]),
                    T.EnsureChannelFirstd(keys=["image", "label"]),
                    T.Lambdad(keys=["image"], func=lambda x: x[channel, None, :, :, :]),
                    T.EnsureTyped(keys=["image", "label"]),
                    T.Orientationd(keys=["image", "label"], axcodes="RAS"),
                    T.Spacingd(keys=["image", "label"], pixdim=(3.0, 3.0, 2.0), mode=("bilinear", "nearest")),
                    T.CenterSpatialCropd(keys=["image", "label"], roi_size=(64, 64, 64)),
                    T.ScaleIntensityRangePercentilesd(keys="image", lower=0, upper=99.5, b_min=0, b_max=1),
                    T.RandSpatialCropd(keys=["image", "label"], roi_size=(64, 64, 1), random_size=False),
                    T.Lambdad(keys=["image", "label"], func=lambda x: x.squeeze(-1)),
                    T.CopyItemsd(keys=["label"], times=1, names=["slice_label"]),
                    T.Lambdad(keys=["slice_label"], func=lambda x: 1.0 if x.sum() > 0 else 0.0),
                ]
            )

            return DecathlonDataset(
                root_dir="/DATA/NAS/datasets_source/brain",
                task="Task01_BrainTumour",
                section="training",
                cache_rate=1.0,  # you may need a few Gb of RAM... Set to 0 otherwise
                num_workers=4,
                download=True,  # Set download to True if the dataset hasnt been downloaded yet
                seed=0,
                transform=train_transforms,
            )
        elif self.data_name == "spider64":
            spider_files = create_spider_files()
            prob = 0.5
            transforms = T.Compose([
                # each image has a single ivd label
                T.LoadImaged(keys=['image', 'mask'], ensure_channel_first=True),
                T.Orientationd(keys=['image', 'mask'], axcodes='RAS'),
                # median dataset spacing
                T.Spacingd(keys=['image', 'mask'],pixdim=(3.32, 0.625, 0.625), mode=("bilinear", "nearest")),
                T.ScaleIntensityRangePercentilesd(keys='image', lower=0, upper=99.5, b_min=0, b_max=1),
                # remove other labels from mask
                CropMaskByLabel(mask_key='mask', label_key='ivd_label', label_lambda_func=lambda x: x + 200),
                # some augmentations
                T.RandGaussianNoised(keys=['image'], mean=0.0, std=0.015, prob=prob),
                T.RandRotated(keys=['image', 'mask'], range_x=30 * (np.pi / 180), mode=["bilinear", "nearest"], prob=prob),
                # center and crop image around ivd
                T.CropForegroundd(keys=['image', 'mask'], source_key='mask', margin=(0, 80, 80), allow_smaller=False),
                T.CenterSpatialCropd(keys=['image', 'mask'], roi_size=(-1, 80, 80)),
                # get a single slice
                T.CenterSpatialCropd(keys=['image', 'mask'], roi_size=(5, -1, -1)),
                T.RandSpatialCropd(keys=['image', 'mask'], roi_size=(1, -1, -1)),
                AssertEmptyImaged(),
                # resize
                T.Resized(keys=['image', 'mask'], spatial_size=(1, 64, 64), anti_aliasing=True),
                T.ToTensord(keys=['image', 'mask']),
                T.SqueezeDimd(keys=['image', 'mask'], dim=1), 
            ])

            return data.CacheDataset(spider_files, transform=transforms)
        else:
            raise NotImplementedError()

    def make_loader(self,
                    dataset,
                    shuffle: bool,
                    num_worker: bool = None,
                    drop_last: bool = True,
                    batch_size: int = None,
                    parallel: bool = False):
        if parallel and distributed.is_initialized():
            # drop last to make sure that there is no added special indexes
            sampler = DistributedSampler(dataset,
                                         shuffle=shuffle,
                                         drop_last=True)
        else:
            sampler = None
        return DataLoader(
            dataset,
            batch_size=batch_size or self.batch_size,
            sampler=sampler,
            # with sampler, use the sample instead of this option
            shuffle=False if sampler else shuffle,
            num_workers=num_worker or self.num_workers,
            pin_memory=True,
            drop_last=drop_last,
            #multiprocessing_context=get_context('fork'),
        )

    def make_model_conf(self):
        if self.model_name == ModelName.beatgans_ddpm:
            self.model_type = ModelType.ddpm
            self.model_conf = BeatGANsUNetConfig(
                attention_resolutions=self.net_attn,
                channel_mult=self.net_ch_mult,
                conv_resample=True,
                dims=2,
                dropout=self.dropout,
                embed_channels=self.net_beatgans_embed_channels,
                image_size=self.img_size,
                in_channels=self.in_channels,
                model_channels=self.net_ch,
                num_classes=None,
                num_head_channels=-1,
                num_heads_upsample=-1,
                num_heads=self.net_beatgans_attn_head,
                num_res_blocks=self.net_num_res_blocks,
                num_input_res_blocks=self.net_num_input_res_blocks,
                out_channels=self.model_out_channels,
                resblock_updown=self.net_resblock_updown,
                use_checkpoint=self.net_beatgans_gradient_checkpoint,
                use_new_attention_order=False,
                resnet_two_cond=self.net_beatgans_resnet_two_cond,
                resnet_use_zero_module=self.
                net_beatgans_resnet_use_zero_module,
            )
        elif self.model_name in [
                ModelName.beatgans_autoenc,
        ]:
            cls = BeatGANsAutoencConfig
            # supports both autoenc and vaeddpm
            if self.model_name == ModelName.beatgans_autoenc:
                self.model_type = ModelType.autoencoder
            else:
                raise NotImplementedError()

            if self.net_latent_net_type == LatentNetType.none:
                latent_net_conf = None
            elif self.net_latent_net_type == LatentNetType.skip:
                latent_net_conf = MLPSkipNetConfig(
                    num_channels=self.style_ch,
                    skip_layers=self.net_latent_skip_layers,
                    num_hid_channels=self.net_latent_num_hid_channels,
                    num_layers=self.net_latent_layers,
                    num_time_emb_channels=self.net_latent_time_emb_channels,
                    activation=self.net_latent_activation,
                    use_norm=self.net_latent_use_norm,
                    condition_bias=self.net_latent_condition_bias,
                    dropout=self.net_latent_dropout,
                    last_act=self.net_latent_net_last_act,
                    num_time_layers=self.net_latent_num_time_layers,
                    time_last_act=self.net_latent_time_last_act,
                )
            else:
                raise NotImplementedError()

            self.model_conf = cls(
                attention_resolutions=self.net_attn,
                channel_mult=self.net_ch_mult,
                conv_resample=True,
                dims=2,
                dropout=self.dropout,
                embed_channels=self.net_beatgans_embed_channels,
                enc_out_channels=self.style_ch,
                enc_pool=self.net_enc_pool,
                enc_num_res_block=self.net_enc_num_res_blocks,
                enc_channel_mult=self.net_enc_channel_mult,
                enc_grad_checkpoint=self.net_enc_grad_checkpoint,
                enc_attn_resolutions=self.net_enc_attn,
                image_size=self.img_size,
                in_channels=self.in_channels,
                model_channels=self.net_ch,
                num_classes=None,
                num_head_channels=-1,
                num_heads_upsample=-1,
                num_heads=self.net_beatgans_attn_head,
                num_res_blocks=self.net_num_res_blocks,
                num_input_res_blocks=self.net_num_input_res_blocks,
                out_channels=self.model_out_channels,
                resblock_updown=self.net_resblock_updown,
                use_checkpoint=self.net_beatgans_gradient_checkpoint,
                use_new_attention_order=False,
                resnet_two_cond=self.net_beatgans_resnet_two_cond,
                resnet_use_zero_module=self.
                net_beatgans_resnet_use_zero_module,
                latent_net_conf=latent_net_conf,
                resnet_cond_channels=self.net_beatgans_resnet_cond_channels,
            )
        else:
            raise NotImplementedError(self.model_name)

        return self.model_conf
