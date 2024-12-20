from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from datalad_core.constraints import Constraint
from datalad_core.repo import (
    Repo,
    Worktree,
)


class Dataset:
    """Dataset parameter type for DataLad command implementations

    Many DataLad commands operate on datasets, which are typically Git
    repositories. This class provides a type to represent this parameter.

    The main purpose of this class is to relay the semantics of the original
    parameter specification all the way to the implementation of a particular
    command. A dataset may be identified in a variety of ways, including
    auto-discovery based on a working directory. Individual commands may want
    to behave differently depending on how a dataset was identified, or if at
    all.

    A second use case are commands that can work on bare repositories and
    worktrees alike. This class is a single type from which the presence of
    both entities can be discovered without code duplication.

    A third use case are to-be-created datasets for which no repository or
    worktree exist on the file system yet, and consequently the
    :class:`~datalad_core.repo.Repo` and :class:`~datalad_core.repo.Worktree`
    classes cannot be used directly.

    .. note::

       Despite the name, this class is very different from the ``Dataset``
       class in legacy DataLad. This is not a convenience interface
       for DataLad commands that operate on datasets. Instead, it is
       merely a type to be used for implementing individual DataLad commands,
       with uniform semantics for this key parameter.
    """

    def __init__(
        self,
        spec: str | Path | Repo | Worktree | None,
    ):
        """
        A ``spec`` is required, even if the given value is ``None``.
        """
        self._spec = spec
        self._repo: Repo | None = None
        self._worktree: Worktree | None = None
        self._path: Path | None = None

    @property
    def pristine_spec(self) -> str | Path | Repo | Worktree | None:
        """Returns the unaltered specification of the dataset

        This is the exact value that has been given to the constructor.
        """
        return self._spec

    @property
    def path(self) -> Path:
        """Returns the local path associated with any (non-)existing dataset

        If an associated Git repository exists on the file system, the return
        path is the worktree root path for non-bare repositories and their
        worktree, or the repository root path for bare repositories.

        If no repository exists, the path is derived from the given ``spec``
        regardless of a corresponding directory existing on the file system.

        If the spec is ``None``, the returned path will be the process working
        directory.
        """
        if self._path is not None:
            return self._path

        if self._spec is None:
            self._path = Path.cwd()
            return self._path

        # use the (resolved) path of a worktree or repo,
        # if they exist.
        # this gives an absolute path
        self._path = (
            self.worktree.path
            if self.worktree
            else self.repo.path
            if self.repo
            else None
        )

        if self._path is not None:
            return self._path

        # there is nothing on the filesystem, we can only work with the
        # pristine_spec as-is
        ps = self.pristine_spec
        if isinstance(ps, Path):
            self._path = ps
        else:
            if TYPE_CHECKING:
                assert isinstance(ps, (Path, str))
            # could be a str-path or some magic label.
            # for now we only support a path specification
            self._path = Path(ps)
        return self._path

    @property
    def repo(self) -> Repo | None:
        """Returns a repository associated with the dataset (if one exists)

        This property is mostly useful for datasets without a worktree.
        For datasets with a worktree it is generally more appropriate
        to access the ``repo`` property of the :attr:`worktree` property.

        Returns ``None`` if there is no associated repository. This may
        happen, if a repository is yet to be created.
        """
        # short cut
        ps = self.pristine_spec

        if self._repo is not None:
            return self._repo

        if self.worktree is not None:
            self._repo = self.worktree.repo
        elif isinstance(ps, Repo):
            self._repo = ps
        elif isinstance(ps, Path):
            self._repo = get_gitmanaged_from_pathlike(Repo, ps)
        elif isinstance(ps, str):
            # could be a str-path or some magic label.
            # for now we only support a path specification
            self._repo = get_gitmanaged_from_pathlike(Repo, ps)
        return self._repo

    @property
    def worktree(self) -> Worktree | None:
        """Returns a worktree associated with the dataset (if one exists)

        Returns ``None`` if there is no associated worktree. This may
        happen, if the dataset is associated with a bare Git repository,
        or if the worktree (and repository) is yet to be created.
        """
        if self._worktree is None:
            ps = self.pristine_spec
            if isinstance(ps, Worktree):
                # we can take this right away
                self._worktree = ps
            elif isinstance(ps, Path):
                self._worktree = get_gitmanaged_from_pathlike(Worktree, ps)
            elif isinstance(ps, str):
                # could be a str-path or some magic label.
                # for now we only support a path specification
                self._worktree = get_gitmanaged_from_pathlike(Worktree, ps)
        return self._worktree

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({self.pristine_spec!r})'


class EnsureDataset(Constraint):
    """Ensure an absent/present `Dataset` from any path or Dataset instance

    Regardless of the nature of the input (`Dataset` instance or local path)
    a resulting instance (if it can be created) is optionally tested for
    absence or presence on the local file system.

    Due to the particular nature of the `Dataset` class (the same instance
    is used for a unique path), this constraint returns a `DatasetParameter`
    rather than a `Dataset` directly. Consuming commands can discover
    the original parameter value via its `original` property, and access a
    `Dataset` instance via its `ds` property.

    In addition to any value representing an explicit path, this constraint
    also recognizes the special value `None`. This instructs the implementation
    to find a dataset that contains the process working directory (PWD).
    Such a dataset need not have its root at PWD, but could be located in
    any parent directory too. If no such dataset can be found, PWD is used
    directly. Tests for ``installed`` are performed in the same way as with
    an explicit dataset location argument. If `None` is given and
    ``installed=True``, but no dataset is found, an exception is raised
    (this is the behavior of the ``required_dataset()`` function in
    the DataLad core package). With ``installed=False`` no exception is
    raised and a dataset instances matching PWD is returned.
    """

    def __init__(self, installed: bool | str | None = None):
        """
        Parameters
        ----------
        installed: bool, optional
          If given, a dataset will be verified to be installed or not.
          Otherwise the installation-state will not be inspected.
        """
        self._installed = installed
        super().__init__()

    @property
    def input_synopsis(self) -> str:
        return '(path to) {}dataset'.format(
            'an existing '
            if self._installed
            else 'a non-existing '
            if self._installed is False
            else 'a '
        )

    def __call__(self, value) -> Dataset:
        ds = Dataset(value)
        try:
            # resolve
            ds.path  # noqa: B018
        except (ValueError, TypeError) as e:
            self.raise_for(
                value,
                'cannot create Dataset from {type}: {__caused_by__}',
                type=type(value),
                __caused_by__=e,
            )
        if self._installed is False and (ds.worktree or ds.repo):
            self.raise_for(ds, 'already exists locally')
        if self._installed and not (ds.worktree or ds.repo):
            self.raise_for(ds, 'not installed')
        if self._installed != 'with-id':
            return ds

        to_query = ds.worktree or ds.repo
        if TYPE_CHECKING:
            assert to_query is not None
        if 'datalad.dataset.id' not in to_query.config.sources['datalad-branch']:
            self.raise_for(ds, 'does not have a datalad-id')
        return ds


def get_gitmanaged_from_pathlike(cls, path):
    if not isinstance(path, Path):
        path = Path(path)
    # the constructor will tell us, if this an instance of the
    # requested class
    try:
        return cls(path)
    except ValueError:
        return None
