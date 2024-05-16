import math
import unittest

import derivatives_solenoid

class TestDerivativesSolenoid(unittest.TestCase):
    def setUp(self):
        self.dx = 0.001

    def test_initialisation(self):
        sol = derivatives_solenoid.DerivativesSolenoid()

    def test_set_fourier_model(self):
        sol = derivatives_solenoid.DerivativesSolenoid()
        try:
            sol.set_fourier_field_model()
            self.assertTrue(False, "Should have thrown")
        except ValueError:
            pass
        sol.set_fourier_field_model(1.0, [])
        sol.set_fourier_field_model(1.0, [1.0])
        sol.set_fourier_field_model(1.0, [1])
        try:
            sol.set_fourier_field_model(1.0, ["badger"])
            self.assertTrue(False, "Should have thrown")
        except ValueError:
            pass

    def test_set_max_derivative(self):
        sol = derivatives_solenoid.DerivativesSolenoid()
        sol.set_max_derivative(2)
        sol.set_max_derivative(0)
        try: 
            sol.set_max_derivative(-1)
            self.assertTrue(False, "Should have thrown")
        except ValueError:
            pass

    def test_on_axis_field(self):
        sol = derivatives_solenoid.DerivativesSolenoid()
        try:
            sol.get_field_value(0, 0, 0, 0)
            self.assertTrue(False, "Should have thrown")
        except:
            pass
        sol.set_fourier_field_model(0.5, [2.0])
        for i in range(10):
            z = i/10.0
            bfield = sol.get_field_value(0.0, 0.0, z, 0.0)
            delta = bfield[2] - 2.0*math.sin(2*math.pi*z/0.5)
            self.assertLess(abs(bfield[0]), 1e-12)
            self.assertLess(abs(bfield[1]), 1e-12)
            self.assertLess(abs(delta), 1e-12)

    def test_on_axis_field_derivatives(self):
        sol = derivatives_solenoid.DerivativesSolenoid()
        sol.set_fourier_field_model(0.5, [2.0, 1.0])
        for iz in range(5):
            z = iz/7.0
            for deriv in range(1, 10):
                analytical = sol.get_on_axis_field(z, deriv)
                numerical = (sol.get_on_axis_field(z+self.dx, deriv-1)-sol.get_on_axis_field(z-self.dx, deriv-1))/2/self.dx
                if numerical > 0.0:
                    self.assertAlmostEqual(analytical/numerical, 1, 3)
                else:
                    self.assertLess(analytical, 1e-3)

    def dbdx(self, field, position, bdim, xdim):
        position[xdim] += self.dx
        b0 = field.get_field_value(position[0], position[1], position[2], 0.0)
        position[xdim] -= 2*self.dx
        b1 = field.get_field_value(position[0], position[1], position[2], 0.0)
        derivative = (b1[bdim]-b0[bdim])/2/self.dx
        position[xdim] += self.dx
        return derivative


    def get_div_b(self, field, position):
        div = 0.0
        for i in range(3):
            div += self.dbdx(field, position, i, i)
        return div

    def get_curl_b_mag(self, field, position):
        curl2 = 0.0
        curl2 += (self.dbdx(field, position, 1, 2)-self.dbdx(field, position, 2, 1))**2
        curl2 += (self.dbdx(field, position, 0, 2)-self.dbdx(field, position, 2, 0))**2
        curl2 += (self.dbdx(field, position, 0, 1)-self.dbdx(field, position, 1, 0))**2
        return curl2**0.5

    def test_off_axis_field(self):
        sol = derivatives_solenoid.DerivativesSolenoid()
        sol.set_fourier_field_model(0.5, [2.0]) # T, m
        for iz in range(0, 2):
            z = 0.1*iz            
            for ir in range(3):
                r = ir/10.0
                for iphi in range(0, 1):
                    phi = math.radians(iphi*36)
                    pos = [r*math.cos(phi), r*math.sin(phi), z]
                    div_b, curl_b = None, None
                    for order in range(5):
                        sol.set_max_derivative(order)
                        bfield = sol.get_field_value(pos[0], pos[1], pos[2], 0.0)
                        div_b = self.get_div_b(sol, pos)
                        curl_b = self.get_curl_b_mag(sol, pos)
                        print(f"i: {order} pos: {pos[0]:8.4g} {pos[1]:8.4g} {pos[2]:8.4g}", end=" ")
                        print(f"bfield: {bfield[0]:10.4g} {bfield[1]:10.4g} {bfield[2]:10.4g}", end=" ")
                        print(f"div: {div_b:10.4g} curl: {curl_b:10.4g}")
                    print()

if __name__ == "__main__":
    unittest.main()
