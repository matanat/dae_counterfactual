# Counterfactual Explanations for Medical Image Classification and Regression using Diffusion Autoencoder

## Abstract
Counterfactual explanations (CEs) aim to enhance the interpretability of machine learning models by illustrating how alterations in input features would affect the resulting predictions. Common CE approaches require an additional model and are typically constrained to binary counterfactuals. In contrast, we propose a novel method that operates directly on the latent space of a generative model, specifically a Diffusion Autoencoder (DAE). This approach offers inherent interpretability by enabling the generation of CEs and the continuous visualization of the model’s internal representation across decision boundaries.

Our method leverages the DAE’s ability to encode images into a semantically rich latent space in an unsupervised manner, eliminating the need for labeled data or separate feature extraction models. We show that these latent representations are helpful for medical condition classification and the ordinal regression of severity pathologies, such as vertebral compression fractures (VCF) and diabetic retinopathy (DR). Beyond binary CEs, our method supports the visualization of ordinal CEs using a linear model, providing deeper insights into the model’s decision-making process and enhancing interpretability.

Experiments across various medical imaging datasets demonstrate the method’s advantages in interpretability and versatility. The linear manifold of the DAE’s latent space allows for meaningful interpolation and manipulation, making it a powerful tool for exploring medical image properties.

![Graphical Abstract](figures/Graphical_Abstract.png)
**Method overview:** The proposed method involves three steps: 
1. Unsupervised training of a generative feature extractor Diffusion Autoencoder (DAE).
2. Supervised training of a binary classifier to detect a pathology and obtain a decision hyperplane.
3. Calibrating a linear regression of the pathology grade to the hyperplane distance of embedded images. 

The method inherently enables the generation of counterfactual explanations (CEs), visualizing the model's representation corresponding to regression grades and smooth progressions in between.

## Citations
If you use this code or find our work useful, please cite our paper:
``
@article{atad2024counterfactual,
  title={Counterfactual Explanations for Medical Image Classification and Regression using Diffusion Autoencoder},
  author={Matan Atad and David Schinz and Hendrik Moeller and Robert Graf and Benedikt Wiestler and Daniel Rueckert and Nassir Navab and Jan S. Kirschke and Matthias Keicher},
  journal={arXiv preprint arXiv:2408.01571},
  year={2024}
}
``

## Acknowledgment
This work uses the DAE implementation provided by the original authors. For more details and the original codebase, visit the [official DAE repository](https://github.com/preechakul/DAE).
