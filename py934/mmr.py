from math import floor, log2
from typing import List

from ethsnarks.field import FQ
from ethsnarks.jubjub import Point

from py934.jubjub import Field
from .constant import G


class MMR:
    @staticmethod
    def leaf_index(position):
        index = 0
        for i, bit in enumerate(reversed(format(position - 1, 'b'))):
            if bit == '1':
                index = index + (2 << i) - 1
        index += 1
        return index

    @staticmethod
    def peak_node_index(position):
        next_leaf_index = MMR.leaf_index(position + 1)
        return next_leaf_index - 1

    @staticmethod
    def peak_existence(width, peak_height) -> bool:
        return width & (1 << (peak_height - 1)) != 0

    @staticmethod
    def max_height(width):
        return floor(log2(width)) + 1

    @staticmethod
    def sibling_map(width, position) -> str:
        covered_width = 0
        sib_map = None
        my_peak_height = None

        # Find which peak the item belongs to & sibling map for it
        max_height = MMR.max_height(width)
        for i in range(max_height):
            # Starts from the left-most peak
            peak_height = max_height - i
            current_peak_width = (1 << (peak_height - 1))
            if MMR.peak_existence(width, peak_height):
                covered_width += current_peak_width

            if covered_width >= position:
                # The leaf belongs to this peak
                reversed_sib_map = format(covered_width - position, '0{}b'.format(peak_height - 1))
                sib_map = reversed_sib_map[::-1]
                my_peak_height = peak_height
                break

        assert sib_map is not None
        assert my_peak_height is not None
        assert len(sib_map) == my_peak_height - 1
        return sib_map


class PedersenMMRProof:
    def __init__(self, root: FQ, width, position, item: Point, peaks: List[Point], siblings: List[Point]):
        self.root = root
        self.width = width
        self.position = position
        self.item = item
        self.peaks = peaks
        self.sibling = siblings
        assert PedersenMMR.inclusion_proof(root, width, position, item, peaks, siblings)

    def __str__(self):
        return "root: {}\n".format(self.root) + \
               "width: {}\n".format(self.width) + \
               "position: {}\n".format(self.position) + \
               "item: {}\n".format(self.item) + \
               "peaks: {}\n".format(self.peaks) + \
               "siblings: {}".format(self.sibling)


class PedersenMMR(MMR):
    def __init__(self, bits=16):
        self.bits = bits
        self.width = 0
        self.items = {}
        self.nodes = {}
        self.peaks = [Point.infinity()] * bits

    @classmethod
    def from_peaks(cls, bits, width, peaks: List[Point]):
        assert len(peaks) == bits
        mmr = cls(bits)
        mmr.width = width
        mmr.peaks = peaks
        # Update branch nodes
        index = 0
        for i in range(len(peaks)):
            peak_height = len(peaks) - i
            if peaks[i] != Point.infinity():
                # Peak exists
                index += (1 << peak_height) - 1
                mmr.nodes[index] = peaks[i]

    @staticmethod
    def peak_bagging(width, peaks: List[Point]) -> FQ:
        root_point = G
        for i in reversed(range(len(peaks))):
            # Starts from the right-most peak
            peak_height = len(peaks) - i
            peak = peaks[i]
            # With the mountain map, check the peak exists or not correctly
            assert (peak == Point.infinity()) is (False if MMR.peak_existence(width, peak_height) else True)
            # Update root point
            root_point = root_point * peak.y
        root_point = root_point * width
        return root_point.y

    @staticmethod
    def peak_update(prev_width, peaks: List[Point], item: Point) -> List[Point]:
        new_width = prev_width + 1
        leaf_node = item * new_width
        cursor = leaf_node
        new_peaks = peaks
        new_peak = None
        for i in reversed(range(len(peaks))):
            # Starts from the right-most peak
            peak_height = len(peaks) - i
            prev_peak = peaks[i]
            # With the mountain map, check the peak exists or not correctly
            assert (prev_peak == Point.infinity()) is \
                   (True if MMR.peak_existence(prev_width, peak_height) else False)
            # Move cursor to the next peak.
            cursor = cursor * prev_peak.y
            # Update new peak
            if not MMR.peak_existence(new_width, peak_height):
                # Peak should be zero
                new_peaks[i] = Point.infinity()
            elif not MMR.peak_existence(prev_width, peak_height):
                assert new_peak is None, "There should be only one new peak"
                new_peaks[i] = cursor
                new_peak = cursor
            else:
                new_peaks[i] = prev_peak

        assert new_peak is not None, "Failed to find new peak"
        return new_peak

    @property
    def root(self) -> FQ:
        return self.peak_bagging(self.width, self.peaks)

    @staticmethod
    def inclusion_proof(root: FQ, width, position, item: Point, peaks: List[Point],
                        siblings: List[Point]) -> bool:
        # Check peak bagging first
        assert PedersenMMR.peak_bagging(width, peaks) == root

        sibling_map = MMR.sibling_map(width, position)
        my_peak_height = len(sibling_map) + 1
        my_peak = peaks[len(peaks) - my_peak_height]

        # Calculate the belonging peak with siblings
        leaf_node = item * position
        cursor = leaf_node
        for i in range(len(sibling_map)):
            is_right_sibling = sibling_map[i] == '1'
            right_node = siblings[i] if is_right_sibling else cursor
            left_node = cursor if is_right_sibling else siblings[i]
            cursor = right_node * left_node.y

        assert cursor == my_peak
        return True

    def get_inclusion_proof(self, position) -> (FQ, FQ, List[Point], Point):
        # variables to return
        width = self.width
        peaks = self.peaks
        siblings = []

        sibling_map = MMR.sibling_map(width, position)
        my_peak_height = len(sibling_map) + 1
        my_peak = peaks[len(peaks) - my_peak_height]

        # Calculate the belonging peak with siblings
        cursor_index = MMR.leaf_index(position)
        for i in range(my_peak_height - 1):
            has_right_sibling = sibling_map[i] == '1'
            if has_right_sibling:
                cursor_index = cursor_index + (2 << i)
                right_sibling_index = cursor_index - 1
                siblings.append(self.nodes[right_sibling_index])
            else:
                cursor_index += 1
                left_sibling_index = cursor_index - (2 << i)
                siblings.append(self.nodes[left_sibling_index])
        siblings = siblings + [Point.infinity()] * (self.bits - len(siblings))

        return PedersenMMRProof(self.root, self.width, position, self.items[position], self.peaks, siblings)

    def append(self, item: Point):
        new_width = self.width + 1
        prev_width = self.width

        # Store leaf node
        # leaf_node = item * new_width
        leaf_node = item * new_width
        leaf_index = MMR.leaf_index(new_width)
        self.items[new_width] = item
        self.nodes[leaf_index] = leaf_node

        # When it is an odd leaf
        if new_width & 1:
            new_peaks = self.peaks
            new_peaks[len(new_peaks) - 1] = leaf_node
        # When it is an even leaf
        else:
            cursor = leaf_node
            cursor_index = leaf_index
            peak_node_index = MMR.peak_node_index(new_width)
            height = 1
            while cursor_index != peak_node_index:
                height = height + 1
                cursor_index = cursor_index + 1
                #
                left_node_index = cursor_index - (1 << (height - 1))
                left_node = self.nodes[left_node_index]
                cursor = cursor * left_node.y
                self.nodes[cursor_index] = cursor

            new_peaks = self.peaks[:-height] + [cursor] + [Point.infinity()] * (height - 1)

        self.peaks = new_peaks
        self.width = new_width