# This file is part of RinohType, the Python document preparation system.
#
# Copyright (c) Brecht Machiels.
#
# Use of this source code is subject to the terms of the GNU Affero General
# Public License v3. See the LICENSE file or http://www.gnu.org/licenses/.

"""
Base classes and exceptions for styled document elements.

* :class:`Style`: Dictionary storing a set of style attributes
* :class:`Styled`: A styled entity, having a :class:`Style` associated with it
* :class:`StyleStore`: Dictionary storing a set of related `Style`s by name
* :const:`PARENT_STYLE`: Special style that forwards style lookups to the parent
                        :class:`Styled`
* :exc:`ParentStyleException`: Thrown when style attribute lookup needs to be
                               delegated to the parent :class:`Styled`
"""


from collections import OrderedDict

from .document import DocumentElement
from .util import cached


__all__ = ['Style', 'Styled', 'StyleSheet', 'ClassSelector', 'ContextSelector',
           'PARENT_STYLE', 'ParentStyleException']


class ParentStyleException(Exception):
    """Style attribute not found. Consult the parent :class:`Styled`."""


class DefaultValueException(Exception):
    """The attribute is not specified in this :class:`Style` or any of its base
    styles. Return the default value for the attribute."""


class Style(dict):
    """"Dictionary storing style attributes.

    Attrributes can also be accessed as attributes."""

    attributes = {}
    """Dictionary holding the supported style attributes for this :class:`Style`
    class (keys) and their default values (values)"""

    def __init__(self, base=None, **attributes):
        """Style attributes are as passed as keyword arguments. Supported
        attributes include those defined in the :attr:`attributes` attribute of
        this style class and those defined in style classes this one inherits
        from.

        Optionally, a `base` (:class:`Style`) is passed, where attributes are
        looked up when they have not been specified in this style.
        Alternatively, if `base` is :class:`PARENT_STYLE`, the attribute lookup
        is forwarded to the parent of the element the lookup originates from.
        If `base` is a :class:`str`, it is used to look up the base style in
        the :class:`StyleStore` this style is stored in."""
        self.base = base
        self.name = None
        self.store = None
        for attribute in attributes:
            if attribute not in self._supported_attributes():
                raise TypeError('%s is not a supported attribute' % attribute)
        super().__init__(attributes)

    @property
    def base(self):
        """Return the base style for this style."""
        if isinstance(self._base, str):
            return self.store[self._base]
        else:
            return self._base

    @base.setter
    def base(self, base):
        """Set this style's base to `base`"""
        self._base = base

    def __repr__(self):
        """Return a textual representation of this style."""
        return '{0}({1}) > {2}'.format(self.__class__.__name__, self.name or '',
                                       self.base)

    def __copy__(self):
        copy = self.__class__(base=self.base, **self)
        if self.name is not None:
            copy.name = self.name + ' (copy)'
            copy.store = self.store
        return copy

    def __getattr__(self, attribute):
        return self[attribute]

    def __getitem__(self, attribute):
        """Return the value of `attribute`.

        If the attribute is not specified in this :class:`Style`, find it in
        this style's base styles (hierarchically), or ultimately raise a
        :class:`DefaultValueException`."""
        try:
            return super().__getitem__(attribute)
        except KeyError:
            if self.base is None:
                raise DefaultValueException
            return self.base[attribute]

    @classmethod
    def _get_default(cls, attribute):
        """Return the default value for `attribute`.

        If no default is specified in this style, get the default from the
        nearest superclass.
        If `attribute` is not supported, raise a :class:`KeyError`."""
        try:
            for super_cls in cls.__mro__:
                if attribute in super_cls.attributes:
                    return super_cls.attributes[attribute]
        except AttributeError:
            raise KeyError("No attribute '{}' in {}".format(attribute, cls))

    @classmethod
    def _supported_attributes(cls):
        """Return a :class:`set` of the attributes supported by this style
        class."""
        attributes = set()
        try:
            for super_cls in cls.__mro__:
                attributes.update(super_cls.attributes.keys())
        except AttributeError:
            return attributes


class ParentStyle(Style):
    """Special style that delegates attribute lookups by raising a
    :class:`ParentStyleException` on each attempt to access an attribute."""

    def __repr__(self):
        return self.__class__.__name__

    def __getitem__(self, attribute):
        raise ParentStyleException


PARENT_STYLE = ParentStyle()
"""Special style that forwards style lookups to the parent of the
:class:`Styled` from which the lookup originates."""


class Styled(DocumentElement):
    """An element that has a :class:`Style` associated with it."""

    style_class = None
    """The :class:`Style` subclass that corresponds to this :class:`Styled`
    subclass."""

    def __init__(self, style=None, parent=None):
        """Associates `style` with this element. If `style` is `None`, an empty
        :class:`Style` is create, effectively using the defaults defined for the
        associated :class:`Style` class).
        A `parent` can be passed on object initialization, or later by
        assignment to the `parent` attribute."""
        super().__init__(parent=parent)
        if (isinstance(style, Style)
                and not isinstance(style, (self.style_class, ParentStyle))):
            raise TypeError('the style passed to {} should be of type {} '
                            '(a {} was passed instead)'
                            .format(self.__class__.__name__,
                                    self.style_class.__name__,
                                    style.__class__.__name__))
        self.style = style

    @property
    def path(self):
        parent = self.parent.path + ' > ' if self.parent else ''
        style = '[{}]'.format(self.style) if self.style else ''
        return parent + self.__class__.__name__ + style

    @cached
    def get_style(self, attribute, document=None):
        try:
            return self.get_style_recursive(attribute, document)
        except DefaultValueException:
            self.warn('Falling back to default style for ({})'
                      .format(self.path))
            return self.style_class._get_default(attribute)

    def get_style_recursive(self, attribute, document=None):
        style = self._style(document)
        if style is None:
            raise DefaultValueException
        try:
            return style[attribute]
        except ParentStyleException:
            return self.parent.get_style_recursive(attribute, document)

    @cached
    def _style(self, document):
        return (self.style if isinstance(self.style, Style)
                else document.styles.find_style(self))


class StyleSheet(OrderedDict):
    """Dictionary storing a set of related :class:`Style`s by name.

    :class:`Style`s stored in a :class:`StyleStore` can refer to their base
    style by name. See :class:`Style`."""

    def __init__(self, name, base=None):
        super().__init__()
        self.name = name
        self.base = base
        self.selectors = {}

    def __getitem__(self, name):
        if name in self:
            return super().__getitem__(name)
        elif self.base is not None:
            return self.base[name]
        else:
            raise KeyError

    def __setitem__(self, name, style):
        style.name = name
        style.store = self
        super().__setitem__(name, style)

    def __call__(self, name, selector, **kwargs):
        self[name] = selector.cls.style_class(**kwargs)
        self.selectors[name] = selector

    def best_match(self, styled):
        max_score, best_match = Specificity(0, 0, 0), None
        for name, selector in self.selectors.items():
            if not isinstance(selector, Selector):
                continue
            score = selector.match(styled)
            if score > max_score:
                best_match = name
                max_score = score
        return max_score, best_match

    def find_style(self, styled):
        max_score, best_match = self.best_match(styled)
        if self.base:
            base_max_score, base_best_match = self.base.best_match(styled)
            if base_max_score > max_score:
                max_score, best_match = base_max_score, base_best_match
        if sum(max_score):
            print("({}) matches '{}'".format(styled.path, best_match))
            return self[best_match]


class Specificity(tuple):
    def __new__(cls, *items):
        return super().__new__(cls, items)

    def __add__(self, other):
        return tuple(a + b for a, b in zip(self, other))

    def __bool__(self):
        return any(self)


class Selector(object):
    def __init__(self, cls):
        self.cls = cls

    def match(self, styled):
        raise NotImplementedError


class ClassSelector(Selector):
    def __init__(self, cls, style_class=None, **attributes):
        super().__init__(cls)
        self.style_class = style_class
        self.attributes = attributes

    def match(self, styled):
        if not isinstance(styled, self.cls):
            return Specificity(False, False, False)
        class_match = 2 if type(styled) == self.cls else 1
        attributes_result = style_class_result = None
        if self.attributes:
            for attribute, value in self.attributes.items():
                if getattr(styled, attribute) != value:
                    attributes_result = False
                    break
            else:
                attributes_result = True
        if self.style_class is not None:
            style_class_result = styled.style == self.style_class

        if False in (attributes_result, style_class_result):
            return Specificity(False, False, False)
        else:
            return Specificity(style_class_result or False,
                               attributes_result or False, class_match)


class ContextSelector(Selector):
    def __init__(self, *selectors):
        super().__init__(selectors[-1].cls)
        self.selectors = selectors

    def match(self, styled):
        total_score = Specificity(0, 0, 0)
        for selector in reversed(self.selectors):
            if styled is None:
                return Specificity(0, 0, 0)
            score = selector.match(styled)
            if not score:
                return Specificity(0, 0, 0)
            total_score += score
            styled = styled.parent
        return total_score
