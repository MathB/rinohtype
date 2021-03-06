# This file is part of RinohType, the Python document preparation system.
#
# Copyright (c) Brecht Machiels.
#
# Use of this source code is subject to the terms of the GNU Affero General
# Public License v3. See the LICENSE file or http://www.gnu.org/licenses/.

"""
Base classes for flowable and floating document elements. These are elements
that make up the content of a document and are rendered onto its pages.

* :class:`Flowable`: Element that is rendered onto a :class:`Container`.
* :class:`FlowableStyle`: Style class specifying the vertical space surrounding
                          a :class:`Flowable`.
* :class:`Floating`: Decorator to transform a :class:`Flowable` into a floating
                     element.
"""


from copy import copy
from itertools import chain, tee

from .dimension import PT
from .layout import (EndOfContainer, DownExpandingContainer, MaybeContainer,
                     VirtualContainer, discard_state)
from .style import Style, Styled


__all__ = ['Flowable', 'FlowableStyle',
           'DummyFlowable', 'WarnFlowable',
           'InseparableFlowables', 'GroupedFlowables', 'StaticGroupedFlowables',
           'LabeledFlowable', 'GroupedLabeledFlowables',
           'Float']


class FlowableException(Exception):
    def __init__(self, flowable):
        self.flowable = flowable


class FlowableStyle(Style):
    """The :class:`Style` for :class:`Flowable` objects. It has the following
    attributes:

    * `space_above`: Vertical space preceding the flowable (:class:`Dimension`)
    * `space_below`: Vertical space following the flowable (:class:`Dimension`)
    * `margin_left`: Left margin (class:`Dimension`).
    * `margin_right`: Right margin (class:`Dimension`).
    """

    attributes = {'space_above': 0,
                  'space_below': 0,
                  'margin_left': 0,
                  'margin_right': 0}


class FlowableState(object):
    """Stores a :class:`Flowable`\'s rendering state, which can be copied. This
    enables saving the rendering state at certain points in the rendering
    process, so rendering can later be resumed at those points, if needed."""

    def __copy__(self):
        raise NotImplementedError


class Flowable(Styled):
    """An element that can be 'flowed' into a :class:`Container`. A flowable can
    adapt to the width of the container, or it can horizontally align itself in
    the container."""

    style_class = FlowableStyle

    def __init__(self, style=None, parent=None):
        """Initialize this flowable and associate it with the given `style` and
        `parent` (see :class:`Styled`)."""
        super().__init__(style=style, parent=parent)

    @property
    def level(self):
        try:
            return self.parent.level
        except AttributeError:
            return 0

    def flow(self, container, last_descender, state=None, **kwargs):
        """Flow this flowable into `container` and return the vertical space
        consumed.

        The flowable's contents is preceded by a vertical space with a height
        as specified in its style's `space_above` attribute. Similarly, the
        flowed content is followed by a vertical space with a height given
        by the `space_below` style attribute."""
        document = container.document
        if not state:
            container.advance(float(self.get_style('space_above', document)))
        margin_left = self.get_style('margin_left', document)
        margin_right = self.get_style('margin_right', document)
        right = container.width - margin_right
        margin_container = DownExpandingContainer('MARGIN', container,
                                                  left=margin_left, right=right)
        width, descender = self.render(margin_container, last_descender,
                                       state=state, **kwargs)
        container.advance(margin_container.cursor)
        try:
            container.advance(float(self.get_style('space_below', document)))
        except EndOfContainer:
            pass
        return margin_left + width + margin_right, descender

    def spans(self):
        yield self

    def split(self):
        yield

    @property
    def font(self):
        """Raises :class:`FlowableException`.
        (accessed when this flowable is embedded in a paragraph)"""
        raise FlowableException(self)

    def render(self, container, descender, state=None):
        """Renders the flowable's content to `container`, with the flowable's
        top edge lining up with the container's cursor. `descender` is the
        descender height of the preceeding line or `None`."""
        raise NotImplementedError


class DummyFlowable(Flowable):
    style_class = None

    def __init__(self, parent=None):
        super().__init__(parent=parent)

    def flow(self, container, last_descender, state=None):
        return 0, last_descender


class WarnFlowable(DummyFlowable):
    def __init__(self, message, parent=None):
        super().__init__(parent=parent)
        self.message = message

    def flow(self, container, last_descender, state=None):
        self.warn(self.message, container)
        return super().flow(container, last_descender, state)


class InseparableFlowables(Flowable):
    def flowables(self, document):
        raise NotImplementedError

    def render(self, container, last_descender, state=None):
        max_flowable_width = 0
        with MaybeContainer(container) as maybe_container, discard_state():
            for flowable in self.flowables(container.document):
                width, last_descender = flowable.flow(maybe_container,
                                                      last_descender)
                max_flowable_width = max(max_flowable_width, width)
        return max_flowable_width, last_descender


class GroupedFlowablesState(FlowableState):
    def __init__(self, flowables, first_flowable_state=None):
        self.flowables = flowables
        self.first_flowable_state = first_flowable_state

    def __copy__(self):
        copy_list_items, self.flowables = tee(self.flowables)
        copy_first_flowable_state = copy(self.first_flowable_state)
        return self.__class__(copy_list_items, copy_first_flowable_state)

    def next_flowable(self):
        return next(self.flowables)

    def prepend(self, flowable, first_flowable_state):
        self.flowables = chain((flowable, ), self.flowables)
        self.first_flowable_state = first_flowable_state


class GroupedFlowablesStyle(FlowableStyle):
    attributes = {'flowable_spacing': 0}


class GroupedFlowables(Flowable):
    style_class = GroupedFlowablesStyle

    def flowables(self, document):
        raise NotImplementedError

    def render(self, container, descender, state=None, **kwargs):
        max_flowable_width = 0
        flowables = self.flowables(container.document)
        item_spacing = self.get_style('flowable_spacing', container.document)
        state = state or GroupedFlowablesState(flowables)
        flowable = state.next_flowable()
        try:
            while True:
                width, descender = \
                    flowable.flow(container, descender,
                                  state=state.first_flowable_state, **kwargs)
                max_flowable_width = max(max_flowable_width, width)
                state.first_flowable_state = None
                flowable = state.next_flowable()
                container.advance(item_spacing)
        except EndOfContainer as eoc:
            state.prepend(flowable, eoc.flowable_state)
            raise EndOfContainer(state)
        except StopIteration:
            return max_flowable_width, descender


class StaticGroupedFlowables(GroupedFlowables):
    def __init__(self, flowables, style=None, parent=None):
        super().__init__(style=style, parent=parent)
        self.children = flowables
        for flowable in flowables:
            flowable.parent = self

    def prepare(self, document):
        super().prepare(document)
        for child in self.children:
            child.prepare(document)

    def flowables(self, document):
        return iter(self.children)


class LabeledFlowableStyle(FlowableStyle):
    attributes = {'label_min_width': 12*PT,
                  'label_max_width': 80*PT,
                  'label_spacing': 3*PT,
                  'wrap_label': False}


class LabeledFlowable(Flowable):
    style_class = LabeledFlowableStyle

    def __init__(self, label, flowable, style=None, parent=None):
        super().__init__(style=style, parent=parent)
        self.label = label
        self.flowable = flowable
        label.parent = flowable.parent = self

    def label_width(self, container):
        virtual_container = VirtualContainer(container)
        label_width, _ = self.label.flow(virtual_container, 0)
        return label_width

    def render(self, container, last_descender, state=None,
               max_label_width=None):
        # TODO: line up baseline of label and first flowable
        label_column_min_width = self.get_style('label_min_width', container.document)
        label_column_max_width = self.get_style('label_max_width', container.document)
        wrap_label = self.get_style('wrap_label', container.document)

        label_width = self.label_width(container)
        max_label_width = max_label_width or label_width
        label_column_width = max(label_column_min_width,
                                 min(max_label_width, label_column_max_width))
        label_spillover = not wrap_label and label_width > label_column_width

        def render_label(container):
            width = None if label_spillover else label_column_width
            label_container = DownExpandingContainer('LABEL', container,
                                                     width=width)
            _, descender = self.label.flow(label_container, last_descender)
            return label_container.cursor, descender

        def render_content(container, descender):
            label_spacing = self.get_style('label_spacing', container.document)
            left = label_column_width + label_spacing
            content_container = DownExpandingContainer('CONTENT', container,
                                                       left=left)
            _, descender = self.flowable.flow(content_container, descender,
                                              state=state)
            return content_container.cursor, descender

        with MaybeContainer(container) as maybe_container:
            if not state:
                with discard_state():
                    label_height, label_desc = render_label(maybe_container)
                    if label_spillover:
                        maybe_container.advance(label_height)
                        last_descender = label_desc
            else:
                label_height = label_desc = 0
            content_height, content_desc = render_content(maybe_container,
                                                          last_descender)
            if label_spillover:
                container.advance(content_height)
                descender = content_desc
            else:
                if content_height > label_height:
                    container.advance(content_height)
                    descender = content_desc
                else:
                    container.advance(label_height)
                    descender = label_desc
        return container.width, descender


class GroupedLabeledFlowables(GroupedFlowables):
    def _calculate_label_width(self, container):
        return max(flowable.label_width(container)
                   for flowable in self.flowables(container.document))

    def render(self, container, descender, state=None):
        if state is None:
            max_label_width = self._calculate_label_width(container)
        else:
            max_label_width = state.max_label_width
        try:
            return super().render(container, descender, state=state,
                                  max_label_width=max_label_width)
        except EndOfContainer as eoc:
            eoc.flowable_state.max_label_width = max_label_width
            raise


class Float(Flowable):
    """Transform a :class:`Flowable` into a floating element. A floating element
    or 'float' is not flowed into its designated container, but is forwarded to
    another container pointed to by the former's :attr:`Container.float_space`
    attribute.

    This is typically used to place figures and tables at the top or bottom of a
    page, instead of in between paragraphs."""

    def __init__(self, flowable, style=None, parent=None):
        super().__init__(style=style, parent=parent)
        self.flowable = flowable
        flowable.parent = self

    def prepare(self, document):
        self.flowable.prepare(document)

    def flow(self, container, last_descender, state=None):
        """Flow contents into the float space associated with `container`."""
        if self not in container.document.floats:
            self.flowable.flow(container.float_space, None)
            container.document.floats.add(self)
            container.page.check_overflow()
        return 0, last_descender
