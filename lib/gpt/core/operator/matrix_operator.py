#
#    GPT - Grid Python Toolkit
#    Copyright (C) 2020  Christoph Lehner (christoph.lehner@ur.de, https://github.com/lehner/gpt)
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License along
#    with this program; if not, write to the Free Software Foundation, Inc.,
#    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
import gpt, sys
from gpt.core.expr import factor

#
# A^dag (A^-1)^dag = (A^-1 A)^dag = 1^\dag = 1
# (A^dag)^-1 = (A^-1)^dag
#
class matrix_operator(factor):

    #
    # lhs = A rhs
    # otype = (lhs.otype,rhs.otype)
    # grid = (lhs.grid,rhs.grid)
    # zero = (lhs.zero,rhs.zero)  <-  initialize opposite temporary to zero?
    #
    def __init__(
        self,
        mat,
        adj_mat=None,
        inv_mat=None,
        adj_inv_mat=None,
        otype=(None, None),
        grid=(None, None),
        zero=(False, False),
        cb=(None, None),
        accept_list=False,
    ):

        self.mat = mat
        self.adj_mat = adj_mat
        self.inv_mat = inv_mat
        self.adj_inv_mat = adj_inv_mat
        self.accept_list = accept_list

        # this allows for automatic application of tensor versions
        # also should handle lists of lattices
        self.otype = otype if type(otype) == tuple else (otype, otype)

        # do we request, e.g., the lhs of lhs = A rhs to be initialized to zero
        # if it is not given?
        self.zero = zero if type(zero) == tuple else (zero, zero)

        # the grids we expect
        self.grid = grid if type(grid) == tuple else (grid, grid)

        # the checkerboards we expect
        self.cb = cb if type(cb) == tuple else (cb, cb)

    def inv(self):
        return matrix_operator(
            mat=self.inv_mat,
            adj_mat=self.adj_inv_mat,
            inv_mat=self.mat,
            adj_inv_mat=self.adj_mat,
            otype=tuple(reversed(self.otype)),
            grid=tuple(reversed(self.grid)),
            zero=tuple(reversed(self.zero)),
            cb=tuple(reversed(self.cb)),
            accept_list=self.accept_list,
        )

    def adj(self):
        return matrix_operator(
            mat=self.adj_mat,
            adj_mat=self.mat,
            inv_mat=self.adj_inv_mat,
            adj_inv_mat=self.inv_mat,
            otype=tuple(reversed(self.otype)),
            grid=tuple(reversed(self.grid)),
            zero=tuple(reversed(self.zero)),
            cb=tuple(reversed(self.cb)),
            accept_list=self.accept_list,
        )

    def __mul__(self, other):

        if type(other) == matrix_operator:
            # mat = self * other
            # mat^dag = other^dag self^dag
            # (mat^dag)^-1 = (other^dag self^dag)^-1 = self^dag^-1 other^dag^-1

            # TODO:
            # Depending on other.zero flag and if self.inv_mat is set, we should
            # attempt to properly propagate dst as well.

            adj_other = other.adj()
            adj_self = self.adj()
            inv_other = other.inv()
            inv_self = self.inv()
            adj_inv_other = adj_other.inv()
            adj_inv_self = adj_self.inv()
            return matrix_operator(
                mat=lambda dst, src: self(dst, other(src)),
                adj_mat=lambda dst, src: adj_other(dst, adj_self(src)),
                inv_mat=lambda dst, src: inv_other(dst, inv_self(src)),
                adj_inv_mat=lambda dst, src: adj_inv_self(dst, adj_inv_other(src)),
                otype=(self.otype[0], other.otype[1]),
                grid=(self.grid[0], other.grid[1]),
                zero=(self.zero[0], other.zero[1]),
                cb=(self.cb[0], other.cb[1]),
                accept_list=True,
            )
        else:
            return gpt.expr(other).__rmul__(self)

    def __rmul__(self, other):
        return gpt.expr(other).__mul__(self)

    def converted(self, to_precision, verbose=False):
        assert all([g is not None for g in self.grid])
        assert all([ot is not None for ot in self.otype])
        grid = tuple([g.converted(to_precision) for g in self.grid])
        otype = self.otype
        zero = self.zero
        cb = self.cb

        def _converted(dst, src, mat, l, r):
            t0 = gpt.time()
            conv_src = [gpt.lattice(self.grid[l], otype[l]) for x in src]
            conv_dst = [gpt.lattice(self.grid[r], otype[r]) for x in src]

            gpt.convert(conv_src, src)
            if zero[l]:
                gpt.convert(conv_dst, dst)
            t1 = gpt.time()
            mat(conv_dst, conv_src)
            t2 = gpt.time()
            gpt.convert(dst, conv_dst)
            t3 = gpt.time()
            if verbose:
                gpt.message(
                    "Converted to",
                    to_precision.__name__,
                    "in",
                    t3 - t2 + t1 - t0,
                    "s, matrix application in",
                    t2 - t1,
                    "s",
                )

        return matrix_operator(
            mat=lambda dst, src: _converted(dst, src, self.mat, 0, 1),
            adj_mat=lambda dst, src: _converted(dst, src, self.adj_mat, 1, 0),
            inv_mat=lambda dst, src: _converted(dst, src, self.inv_mat, 1, 0),
            adj_inv_mat=lambda dst, src: _converted(dst, src, self.adj_inv_mat, 0, 1),
            otype=otype,
            grid=grid,
            zero=zero,
            cb=cb,
            accept_list=True,
        )

    def unary(self, u):
        if u == gpt.factor_unary.BIT_TRANS | gpt.factor_unary.BIT_CONJ:
            return self.adj()
        elif u == gpt.factor_unary.NONE:
            return self
        assert 0

    def __call__(self, first, second=None, *extra):
        assert self.mat is not None

        return_list = type(first) == list
        first = gpt.util.to_list(first)

        if second is None:
            src = first
        else:
            dst = first
            src = gpt.util.to_list(second)

        type_match = (
            self.otype[1] is None or self.otype[1].__name__ == src[0].otype.__name__
        )

        if second is None:
            if self.grid[0] is None or not type_match:
                dst_grid = src[0].grid
                dst_otype = src[0].otype
                # if types do not match or are not provided, assume mat : X -> X
            else:
                dst_grid = self.grid[0]
                dst_otype = self.otype[0]

            dst = [gpt.lattice(dst_grid, dst_otype) for x in src]
            if self.cb[0] is not None:
                for x in dst:
                    x.checkerboard(self.cb[0])

            if self.zero[0]:
                for x in dst:
                    x[:] = 0

        if self.accept_list:
            mat = self.mat
        else:

            def mat(dst, src, *extra):
                assert len(dst) == len(src)
                for idx in range(len(dst)):
                    self.mat(dst[idx], src[idx], *extra)

        if type_match:
            mat(dst, src, *extra)
        else:
            self.otype[1].distribute(mat, dst, src, *extra, zero_lhs=self.zero[0])

        if not return_list:
            return gpt.util.from_list(dst)

        return dst
