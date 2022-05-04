import json
import sys
import shutil
import os
import math
import numpy
import scipy.integrate
import scipy.interpolate
import scipy.fft
import matplotlib.pyplot
import ROOT
from field_models import FieldSum
from field_models import FlatGaussField
from field_models import LinearInterpolation
from field_models import SineField
from field_models import UniformField
from field_models import CurrentSheet


"""
Two classes to evolve the beta function
BetaFinder - uses a second order differential equation
BetaFinder2 - integrates a transfer matrix

Some plotting routines as well

Units are T, GeV/c, m
"""

class BetaFinder(object):
    """
    Calculate transfer matrix by evolving infinitesimal (decoupled) TM

    Find the periodic solution using the usual alpha/beta relationship (if phase advance real)
    """
    def __init__(self, field, momentum):
        """
        Initialise
        - field is an object of type field_models.Field
        - momentum is a float (momentum in GeV/c)
        """
        self.field_model = field
        self.period = self.field_model.get_period()
        self.momentum = momentum
        self.hmax = self.period*1e-4
        self.verbose = 0
        self.q = 1

    def field(self, z):
        """
        Return the field at position z
        """
        return self.field_model.get_field(z)

    def matrix_derivatives(self, y, z):
        """
        Returns dM/dz at position z given M
        - y is a list of floats like M[0,0], M[0,1], M[1,0], M[1,1], larmor_angle
        - z is a float z position [m]
        Returns a list of floats derivatives with respect to z of 
        M[0,0], M[0,1], M[1,0], M[1,1], larmor_angle 
        (for input into scipy.odeint)
        """
        pz = self.momentum
        bz = self.field(z)
        q = 1
        b0 = 0.3*q*bz
        matrix = numpy.array([[y[0], y[1]], [y[2], y[3]]])
        dmatrix = numpy.array([[0.0, 1/pz], [-b0 **2/4.0/pz, 0.0]])
        mderiv = numpy.dot(dmatrix, matrix)
        delta_matrix = (mderiv[0,0], mderiv[0,1], mderiv[1,0], mderiv[1,1], -b0/2/pz)
        return delta_matrix

    def get_beta_periodic(self):
        """
        Returns a tuple of (beta, alpha, phase advance) where:
        - beta is in [m]
        - phase_advance is in [rad]
        beta should be periodic, so beta at the start of one period is the same 
        as beta at the end of one period. If there is no solution, returns (0,0,0)
        """
        zout = [0.0, self.period]
        matrix = scipy.integrate.odeint(self.matrix_derivatives,
                                        [1, 0.0, 0.0, 1.0, 0.0], # m_00 m_01 m_10 m_11 larmor
                                        zout, hmax=self.hmax,
                                        mxstep=int(zout[-1]/self.hmax*2))[-1]
        larmor_angle = matrix[4]
        m2d = numpy.array([[matrix[0], matrix[1]], [matrix[2], matrix[3]]])
        cosmu = (m2d[0,0]+m2d[1,1])/2
        #print("Transfer matrix with cosmu", cosmu, "det", numpy.linalg.det(m2d), "\n", m2d)
        if abs(cosmu) > 1:
            return (0.0, 0.0, 0.0)
        n2d = m2d - numpy.array([[cosmu, 0.0],[0.0,cosmu]])
        #print("N2D\n", n2d)
        # absolute value of sin(mu) from square root; we use beta is pos definite to force the sign of sinmu
        sinmu = numpy.linalg.det(n2d)**0.5*numpy.sign(n2d[0,1]) 
        n2d /= sinmu
        #print("N2D over sinmu with sinmu=", sinmu, "\n", n2d)
        v2d = numpy.array([[n2d[0,1], -n2d[0,0]], [-n2d[0,0], -n2d[1, 0]]])
        # v2d[0,0] = beta/p
        beta, alpha, phase_advance = v2d[0, 0]*self.momentum, -v2d[0,1], math.atan2(cosmu, sinmu)
        #print("beta alpha phi", beta, alpha, phase_advance)
        return beta, alpha, phase_advance

    def beta_derivatives(self, y, z):
        """
        Returns a tuple of optical parameters like (dbeta/dz, d2beta/dz2, dphi/dz)
        - y is a list like [beta, dbeta/dz, phi] with units [m], [], [radians]
        - z is z-position in [m]
        phi is the phase advance. This is used by odeint to evolve beta/etc
        """

        pz = self.momentum
        bz = self.field(z)
        kappa = 0.15*bz/pz
        Ltwiddle = 0
        beta = y[0]
        dbetadz = y[1]
        d2betadz2 = +(dbetadz)**2 \
                    -4*beta**2*kappa**2 \
                    +4*(1+Ltwiddle**2)
        d2betadz2 = d2betadz2/(2*beta)
        dphidz = 1/beta
        dydz = (dbetadz, d2betadz2, dphidz)
        if self.verbose > 0:
            print("beta derivatives z:", z, "bz:", bz, "k:", kappa, "y:", y, "dy/dz:", dydz)
        return dydz

    def evolve(self, beta0, dbetadz0, zout):
        """
        Calculates beta, dbeta/dz, phi at some position zout
        - beta0: initial optical beta function
        - dbetadz0: initial derivative of optical beta function
        - zout: final z position
        Returns a tuple of beta, dbeta.dz, phi with units [m], [], [rad]
        """
        zout = [0.0, zout]
        output = scipy.integrate.odeint(self.beta_derivatives,
                                        [beta0, dbetadz0, 0.],
                                        zout, hmax=self.hmax,
                                        mxstep=int(zout[-1]/self.hmax*2))
        return output[-1]

    def is_not_periodic(self, beta0, beta1):
        """
        Check if beta0 and beta1 are the same within tolerances
        """
        test_out = abs(beta0-beta1)*2/(beta0+beta1) > 0.05 or abs(beta0-beta1) > 1
        if test_out:
            print("Not periodic", self.momentum, beta0-beta1, abs(beta0-beta1)*2/(beta0+beta1), test_out)
        return test_out

    def minuit_fitter(self, seed_beta0, err_beta0, max_beta0, n_iterations, tolerance):
        """
        Drive minuit to find a periodic beta function
        - called by get_beta_periodic_minuit
        """
        self.minuit = ROOT.TMinuit()
        self.minuit.SetPrintLevel(-1)
        self.minuit.DefineParameter(0, "beta0", seed_beta0, err_beta0, 0.0, max_beta0)
        self.minuit.SetFCN(self.score_function)
        self.minuit.Command("SIMPLEX "+str(n_iterations)+" "+str(tolerance))
        beta0 = self.score_function(0, 0, [0], 0, 0)
        return beta0

    def score_function(self, nvar, parameters, score, jacobian, err):
        """
        Minuit score function used by the minuit root finding routines
        """
        beta0 = ROOT.Double()
        err = ROOT.Double()
        self.minuit.GetParameter(0, beta0, err)
        beta1, dbetadz, phi = self.evolve(float(beta0), 0., self.period)
        score[0] = abs(beta1-beta0)+abs(dbetadz*100)**2
        #print (beta0, beta1, dbetadz, score[0])
        return beta0, beta1, dbetadz, phi

    def get_beta_periodic_minuit(self, seed_beta0):
        """
        A slow alternative to the transfer matrix approach to get_beta_periodic.
        Use minuit to try to find a periodic beta function numerically.
        - seed_beta0: guess at initial periodic beta function
        Returns a tuple of beta(z=0), beta(z=period/2), phase_advance. If no 
        solution is found, returns (0.0, 0.0, 0.0)
        """
        beta0, beta1, dbetadz, phi = self.minuit_fitter(seed_beta0, seed_beta0/10., 100.0, 500, 1e-5)
        print(format(self.momentum, "8.4g"), format(beta0, "12.6g"), format(beta1, "12.6g"), dbetadz, abs(beta0-beta1)*2.0/(beta0+beta1))
        if self.is_not_periodic(beta0, beta1):
            return 0.0, 0.0, 0.0
        return beta1, dbetadz, phi

    def propagate_beta(self, beta0, dbetadz0, n_points=101):
        """
        Propagate beta and return a tuple of lists with beta as a function of z
        - beta0: initial beta
        - dbetadz0: initial derivative of beta w.r.t. z
        - n_points: number of z points
        Returns a tuple like 
        - z_list: list of z positions
        - beta_list: list of beta 
        - dbetadz_list: list of first derivatives of beta
        - phi_list: list of phase advance
        """
        z_list = [self.period*i/float(n_points-1) for i in range(n_points)]
        output_list = []
        out, infodict = scipy.integrate.odeint(self.beta_derivatives,
                                     [beta0, dbetadz0, 0.],
                                     z_list, hmax=self.hmax, full_output=True,
                                     mxstep=int(z_list[-1]/self.hmax*2))
        if self.verbose > 0:
            for key, value in infodict.items():
                print(key, value)
        output_list = out
        #print(z, self.momentum, output_list[-1])
        beta_list = [output[0] for output in output_list]
        dbetadz_list = [output[1] for output in output_list]
        phi_list = [output[2] for output in output_list]
        return z_list, beta_list, dbetadz_list, phi_list


def clear_dir(a_dir):
    try:
        shutil.rmtree(a_dir)
    except OSError:
        pass
    os.makedirs(a_dir)

fignum = 1
def do_plots(field, pz0, pz_list, plot_dir):
    """
    Plot the beta function for a given field model
    - field: the field model. Should be of type field_model.Field
    - pz0: a reference momentum for plotting vs z
    - pz_list: a set of pz values for finding the periodic solution and plotting
               vs pz
    """
    global fignum
    #matplotlib.rcParams['text.usetex'] = True
    bsquared = None
    period = field.get_period()
    beta_list = []
    antibeta_list = []
    phi_list = []
    beta_finder = BetaFinder(field, 1.)
    if bsquared != None:
        beta_finder.field_model.normalise_bz_squared(bsquared)
    z_list = [i*period/1000 for i in range(1001)]
    bz_list = [beta_finder.field_model.get_field(z) for z in z_list]
    bz2_list = [bz**2 for bz in bz_list]
    figure = matplotlib.pyplot.figure(fignum, figsize=(12, 10))
    figure.suptitle("$"+field.human_readable()+"$")
    fignum += 1
    if len(figure.get_axes()) == 0:
        axes = [figure.add_subplot(2, 2, 1), figure.add_subplot(2, 2, 2),
                figure.add_subplot(2, 2, 3), figure.add_subplot(2, 2, 4)]
        axes.append(axes[1].twinx())
    else:
        axes = figure.get_axes()
    zero_list = [0. for i in z_list]
    #axes[0].plot(z_list, zero_list, '--g')
    axes[0].plot(z_list, bz_list)
    axes[0].set_xlabel("z [m]")
    axes[0].set_ylabel("B$_{z}$ [T]")
    axes[1].plot(z_list, bz2_list)
    axes[1].set_xlabel("z [m]")
    axes[1].set_ylabel("B$_{z}^2$ [T$^2$]")

    print("     pz    beta_0     phi      n_iterations")
    for pz in pz_list:
        beta_finder.momentum = pz
        #beta, antibeta, phi = beta_finder.get_beta_periodic(beta)
        beta, alpha, phi = beta_finder.get_beta_periodic()
        print ("    ", pz, beta, phi)
        beta_list.append(beta)
        antibeta_list.append(0.0)
        phi_list.append(phi)
    axes[2].plot(pz_list, beta_list, label="$\\beta(L)$")
    #axes[1].plot(pz_list, antibeta_list, 'g--', label="$\\beta(L/2)$")
    axes[2].set_xlabel("p$_{z}$ [GeV/c]")
    axes[2].set_ylabel("$\\beta$ [m]")
    axes[2].set_ylim([0.0, 0.5])
    """
    axes[4].set_ylabel("$\\phi$ [rad]", color='r')
    axes[4].tick_params(axis='y', labelcolor='r')
    for i in range(int(min(phi_list)/math.pi)+1, int(max(phi_list)/math.pi)+1):
        pi_list = [i*math.pi, i*math.pi]
        pi_pz_list = [min(pz_list), max(pz_list)]
        label = None
        if i == 0:
            label = "$\\phi$"
        #axes[4].plot(pi_pz_list, pi_list, ':', color='pink', label=label)
    #axes[4].plot(pz_list, phi_list, 'r-.')
    """

    for pz in [pz0]:
        beta_finder.momentum = pz
        beta, alpha, phi = beta_finder.get_beta_periodic()
        if beta < 1e-9:
            continue
        beta_finder.verbose = 0
        z_list, beta_list, dbetadz_list, phi_list = \
                                        beta_finder.propagate_beta(beta, 0.)
        axes[3].plot(z_list, beta_list, label="p$_z$ "+format(pz, "6.4g")+" GeV/c")
        axes[3].set_xlabel("z [m]")
        axes[3].set_ylabel("$\\beta$ [m]")
        axes[3].set_ylim([0.0, 0.5])
        axes[3].legend()

    emittance = 0.0003 # metres
    mass = 0.105658 # GeV/c^2
    #for emittance in [0.0003]:
        #sigma_x_list = [(beta*emittance*mass/beta_finder.momentum)**0.5 for beta in beta_list]
        #axes[3].plot(z_list, sigma_x_list)
    #axes[3].grid(1)
    #axes[3].set_xlabel("z [m]")
    #axes[3].set_ylabel("$\\sigma_x$ [m]")
    name = "optics_L_"+str(period)+field.get_name()+"_pz_"+str(pz)+".png"
    figure.savefig(os.path.join(plot_dir, name))

def make_sine_field(sol_bz2, bz1, bz2, bz3):
    factor = 1
    period = 1.0
    bz0 = 0.0
    #bz1 = 7.206
    #bz2 = 1.0
    #bz3 = 0.0
    f = SineField(factor*bz0, factor*bz1, factor*bz2, factor*bz3, period)#
    if sol_bz2 > 0:
        f_bz2 = f.get_bz2_int()
        factor = (sol_bz2/f_bz2)**0.5
        f = SineField(factor*bz0, factor*bz1, factor*bz2, factor*bz3, period)#
    return f


def make_solenoid_field():
    #b0, zcentre, length, radius, period, nrepeats
    period = 1.0
    bz0 = 7.206
    field_list = [(1.0, 0.1, 0.1, 0.4)]
    solenoid_list = [CurrentSheet(b0, z0, l0, r0, period, 4) for b0, z0, l0, r0 in field_list]
    solenoid_list += [CurrentSheet(-b0, -z0, l0, r0, period, 4) for b0, z0, l0, r0 in field_list]
    field_sum = FieldSum(solenoid_list)
    bz_norm = max([field_sum.get_field(i*period/100.0) for i in range(101)])
    for field in field_sum.field_list:
        field.b0 = field.b0*bz0/bz_norm # watch the sign on the field
    bz_norm = max([field_sum.get_field(i*period/100.0) for i in range(101)])
    return field_sum

def fft_field(truncation):
    source_field = make_solenoid_field()
    period = source_field.get_period()
    field_values = [source_field.get_field(i*period/100.0) for i in range(100)]
    my_fft = scipy.fft.fft(field_values)
    trunc_fft = [x if i < truncation else 0.0 for i, x in enumerate(my_fft)]
    inverse = numpy.real(scipy.fft.ifft(trunc_fft))
    interpolation = LinearInterpolation(inverse, period)
    interpolation.name = "fft_truncated_"+str(interpolation)
    print(trunc_fft, inverse)
    return interpolation

def main():
    global fignum
    plot_dir = "optics-scan_v1"
    pz_list = [pz_i/1000. for pz_i in range(100, 301, 5)]
    sol_field = make_solenoid_field()
    n_points = 25
    clear_dir(plot_dir)
    for i in range(0, n_points):
        bz1 = 12 # 10-abs(i)
        bz2 = i
        bz3 = 0
        #sol_field.get_bz2_int()
        sine_field = make_sine_field(-1, bz1, bz2, bz3)
        # 25 for bz1, bz2 optimisation
        #100 for bz1, bz3 optimisation
        sine_field.normalise_bz_squared(35)
        do_plots(sine_field, 0.2, pz_list, plot_dir)
        print("Bz2", sine_field.get_bz2_int(), sine_field.human_readable(), "\n")
    #fft_field(10000)
    #do_plots(fft_field(10000), 0.2, pz_list)
    fignum -= 1
    matplotlib.pyplot.show(block=False)

if __name__ == "__main__":
    main()
    input("Press <CR> to end")