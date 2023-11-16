import torch
import torch.nn as nn

from manageMIDI import binarize_predictions

class Encoder(nn.Module):
    def __init__(self, net_for_sequence, input_dim, hidden_dim, latent_dim, num_layers=2, batch_first=True, bidirectional=False, cell=False):
        super(Encoder, self).__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.latent_dim = latent_dim
        self.num_layers = num_layers
        self.bidirectional = bidirectional
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.net = net_for_sequence(input_size=input_dim, hidden_size=hidden_dim, num_layers=num_layers, batch_first=batch_first, bidirectional=bidirectional)
        self.fc_mu = nn.Linear(hidden_dim, latent_dim)  # mu = la media della distribuzione latente
        self.fc_logvar = nn.Linear(hidden_dim, latent_dim)  # logvar = logaritmo della varianza
        self.cell = cell

    def forward(self, x):
        batch_size, seq_len, feature_dim = x.shape
        _, h_n = self.net(x)
        if self.cell == True:
            hidden = h_n[0][-1]
        else:
            hidden = h_n[-1]
        enc_h = hidden.view(batch_size, self.hidden_dim).to(self.device)
        mu = self.fc_mu(enc_h)
        logvar = self.fc_logvar(enc_h)
        return mu, logvar, h_n

    def __str__(self):
        string = f"Encoder: {self.net}"
        return string



class Decoder(nn.Module):
    def __init__(self, net_for_sequence, latent_dim, hidden_dim, output_dim, num_layers=2, batch_first=True, bidirectional=False):
        super(Decoder, self).__init__()
        self.output_dim = output_dim
        self.hidden_dim = hidden_dim
        self.latent_dim = latent_dim
        self.num_layers = num_layers
        self.bidirectional = bidirectional
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.net = net_for_sequence(input_size=latent_dim, hidden_size=hidden_dim, num_layers=num_layers, batch_first=batch_first, bidirectional=bidirectional)
        self.fc_output = nn.Linear(hidden_dim, output_dim)


    def forward(self, z, h_0, seq_len):
        '''hidden = self.fc_hidden(z).unsqueeze(0)
        cell = self.fc_cell(z).unsqueeze(0)
        h_n = (hidden.contiguous(), cell.contiguous())'''
        z = z.unsqueeze(1).repeat(1, seq_len, 1)
        z = z.view(z.shape[0], seq_len, self.latent_dim).to(self.device)
        output, _ = self.net(z, h_0)
        reconstructed = self.fc_output(output)
        return reconstructed, h_0

    def __str__(self):
        string = f"Decoder: {self.net}"
        return string

class InitialHiddenGenerator(nn.Module):
    def __init__(self, z_size, hidden_size, num_layers, bias=False):
        super(InitialHiddenGenerator, self).__init__()
        self.num_layer = num_layers
        self.layers = []
        for i in range(0, num_layers):
            self.layers.append(nn.Linear(z_size, hidden_size, bias=bias))
        #self.relu = nn.ReLU()

    def forward(self, z):
        # Passa z attraverso il layer lineare per generare l'hidden state iniziale
        hidden = self.layers[0](z.unsqueeze(0))
        for i in range(1, self.num_layer):
            tmp = self.layers[i](z.unsqueeze(0))
            hidden = torch.cat((hidden, tmp), dim=0)
        #hidden = self.relu(hidden)
        return hidden

# Definizione del modello VAE
class VAE(nn.Module):
    def __init__(self, net_for_sequence):
        super(VAE, self).__init__()
        self.net_for_sequence = net_for_sequence

    def parametersInitialization(self,  input_dim, hidden_dim, latent_dim, num_layers=2, cell=False):
        # Encoder
        self.encoder = Encoder(self.net_for_sequence, input_dim, hidden_dim, latent_dim, num_layers=num_layers, cell=cell)

        # Decoder
        self.decoder = Decoder(self.net_for_sequence, latent_dim, hidden_dim, input_dim, num_layers=num_layers)

        self.fc_hidden = InitialHiddenGenerator(latent_dim, hidden_dim, num_layers)
        self.fc_cell = InitialHiddenGenerator(latent_dim, hidden_dim, num_layers)


    def encode(self, x):
        return self.encoder(x)

    def reparameterize(self, mu, logvar):
        std = torch.exp(0.5 * logvar)
        eps = torch.randn_like(std)
        return mu + eps * std

    def decode(self, z, seq_len):
        h_0 = self.generate_initial_states(z)
        return self.decoder(z, h_0, seq_len)

    def forward(self, x):
        batch_size, seq_len, feature_dim = x.shape
        mu, logvar, h_enc = self.encode(x)
        z = self.reparameterize(mu, logvar)
        reconstruct_output, h_decod = self.decode(z, seq_len)
        return reconstruct_output, mu, logvar, h_enc, h_decod

    def generate_initial_states(self, z):
        # Generate initial hidden and cell states from z
        hidden_state = self.fc_hidden(z)
        cell_state = self.fc_cell(z)
        return hidden_state, cell_state

    def hiddenStateParameters(self):
        return list(self.fc_hidden.parameters()) + list(self.fc_cell.parameters())

    def VAEParameters(self):
        return list(self.decoder.parameters()) + list(self.encoder.parameters())

    def __str__(self):
        string = f"VAE Model: \n> {self.encoder.__str__()}\n> {self.decoder.__str__()}"
        return string


# Funzione di perdita (Loss)
def loss_function_VAE(output, x, beta=0.1):
    recon_x, mu, logvar, h_enc, h_dec = output
    #hidden_loss = nn.functional.mse_loss(h_dec[0], h_enc[0])
    #cell_loss = nn.functional.mse_loss(h_dec[1], h_enc[1])
    '''hidden_loss = nn.functional.binary_cross_entropy_with_logits(h_dec[0], h_enc[0], reduction='none')
    HL = torch.sum(hidden_loss, dim=2).mean()'''
    bce_loss = nn.functional.binary_cross_entropy_with_logits(recon_x, x, reduction='none')
    BCE = torch.sum(bce_loss, dim=2).mean()
    var = logvar.exp()
    KLD = -0.5 * torch.sum(1 + torch.log(var.pow(2)) - mu.pow(2) - var.pow(2))

    total_loss = (BCE + beta * KLD) #+ HL #+ cell_loss
    return BCE, total_loss



def loss_function_hidden(output, x, beta=0):
    recon_x, mu, logvar, h_enc, h_dec = output
    hidden_loss = nn.functional.cross_entropy(h_dec[0], h_enc[0])
    cell_loss = nn.functional.cross_entropy(h_dec[1], h_enc[1])
    return torch.zeros(1, 1),  hidden_loss + cell_loss


