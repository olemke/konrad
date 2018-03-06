# -*- coding: utf-8 -*-
"""Module containing classes describing different surface models.
"""
import abc
import logging

import netCDF4
import numpy as np
from xarray import Dataset, DataArray

from . import (constants, utils)


__all__ = [
    'Surface',
    'SurfaceFixedTemperature',
    'SurfaceHeatCapacity',
    'SurfaceHeatSink',
]


logger = logging.getLogger()


class Surface(Dataset, metaclass=abc.ABCMeta):
    """Abstract base class to define requirements for surface models."""
    def __init__(self, albedo=0.2, temperature=288., height=0.):
        """Initialize a surface model.

        Parameters:
            albedo (float): Surface albedo. The default value of 0.2 is a
                decent choice for clear-sky simulation in the tropics.
            temperature (float): Surface temperature [K].
            height (float): Surface height [m].
        """
        super().__init__()
        self['albedo'] = albedo
        self['time'] = [0]
        self['height'] = height
        self['temperature'] = DataArray(np.array([temperature]),
                                        dims=('time',),
                                        )

        # The surface pressure is initialized before the first iteration
        # within the RCE framework to ensure a pressure that is consistent
        # with the atmosphere used.
        self['pressure'] = None

        utils.append_description(self)

    @abc.abstractmethod
    def adjust(self, sw_down, sw_up, lw_down, lw_up, timestep):
        """Adjust the surface according to given radiative fluxes.

        Parameters:
            sw_down (float): Shortwave downward flux [W / m**2].
            sw_up (float): Shortwave upward flux [W / m**2].
            lw_down (float): Longwave downward flux [W / m**2].
            lw_up (float): Longwave upward flux [W / m**2].
            timestep (float): Timestep in days.
        """
        pass

    @classmethod
    def from_atmosphere(cls, atmosphere, **kwargs):
        """Initialize a Surface object using the lowest atmosphere layer.

        Parameters:
            atmosphere (konrad.atmosphere.Atmosphere): Atmosphere model.
        """
        # Extrapolate surface height from geopotential height of lowest two
        # atmospheric layers.
        z = atmosphere['z'].values[0, :]
        z_sfc = z[0] + 0.5 * (z[0] - z[1])

        # Calculate the surface temperature following a linear lapse rate.
        # This prevents "jumps" after the first iteration, when the
        # convective adjustment is applied.
        lapse = atmosphere.lapse.get(atmosphere)[0]
        t_sfc = atmosphere['T'].values[0, 0] + lapse * (z[0] - z_sfc)

        return cls(temperature=t_sfc,
                   height=z_sfc,
                   **kwargs,
                   )

    @classmethod
    def from_netcdf(cls, ncfile, timestep=-1, **kwargs):
        """Create a surface model from a netCDF file.

        Parameters:
            ncfile (str): Path to netCDF file.
            timestep (int): Timestep to read (default is last timestep).
        """
        with netCDF4.Dataset(ncfile) as dataset:
            t = dataset.variables['temperature'][timestep]
            z = dataset.variables['height'][timestep]

        # TODO: Should other variables (e.g. albedo) also be read?
        return cls(temperature=t, height=z, **kwargs)


class SurfaceFixedTemperature(Surface):
    """Surface model with fixed temperature."""
    def adjust(self, *args, **kwargs):
        """Do not adjust anything for fixed temperature surfaces.

        This function takes an arbitrary number of positional arguments and
        keyword arguments and does nothing.

        Notes:
            Dummy function to fulfill abstract class requirements.
        """
        return


class SurfaceHeatCapacity(Surface):
    """Surface model with adjustable temperature.

    Parameters:
          cp (float): Heat capacity [J kg^-1 K^-1 ].
          rho (float): Soil density [kg m^-3].
          dz (float): Surface thickness [m].
          **kwargs: Additional keyword arguments are passed to `Surface`.
    """
    def __init__(self, *args, cp=1000, rho=1000, dz=100, **kwargs):
        super().__init__(*args, **kwargs)
        self['cp'] = cp
        self['rho'] = rho
        self['dz'] = dz

        utils.append_description(self)

    def adjust(self, sw_down, sw_up, lw_down, lw_up, timestep):
        """Increase the surface temperature by given heatingrate.

        Parameters:
            sw_down (float): Shortwave downward flux [W / m**2].
            sw_up (float): Shortwave upward flux [W / m**2].
            lw_down (float): Longwave downward flux [W / m**2].
            lw_up (float): Longwave upward flux [W / m**2].
            timestep (float): Timestep in days.
        """
        timestep *= 24 * 60 * 60  # Convert timestep to seconds.

        net_flux = (sw_down - sw_up) + (lw_down - lw_up)

        logger.debug(f'Net flux: {net_flux:.2f} W /m^2')

        self['temperature'] += (timestep * net_flux /
                                (self.cp * self.rho * self.dz))

        logger.debug('Surface temperature: '
                     f'{self.temperature.values[0]:.4f} K')


class SurfaceHeatSink(SurfaceHeatCapacity):

    def __init__(self, *args, heat_flux=0, **kwargs):
        """Surface model with adjustable temperature.

        Parameters:
            heat_flux (float): 
        """
        super().__init__(*args, **kwargs)
        self['heat_flux'] = heat_flux

        utils.append_description(self)

    def adjust(self, sw_down, sw_up, lw_down, lw_up, timestep):
        """Increase the surface temperature using given radiative fluxes. Take
        into account a heat sink at the surface, as if heat is transported out
        of the tropics we are modelling.

        Parameters:
            sw_down (float): Shortwave downward flux [W / m**2].
            sw_up (float): Shortwave upward flux [W / m**2].
            lw_down (float): Longwave downward flux [W / m**2].
            lw_up (float): Longwave upward flux [W / m**2].
            timestep (float): Timestep in days.
        """
        timestep *= 24 * 60 * 60  # Convert timestep to seconds.

        net_flux = (sw_down - sw_up) + (lw_down - lw_up)
        sink = self.heat_flux

        logger.debug(f'Net flux: {net_flux:.2f} W /m^2')

        self['temperature'] += (timestep * (net_flux - sink) /
                                (self.cp * self.rho * self.dz))

        logger.debug('Surface temperature: '
                     f'{self.temperature.values[0]:.4f} K')