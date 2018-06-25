"""
Extended base class for oversampling.
"""

# Author: Georgios Douzas <gdouzas@icloud.com>
# License: BSD 3 clause

from math import ceil
from abc import abstractmethod
from collections import Counter
import numpy as np
import pandas as pd
from sklearn.utils import check_random_state
from imblearn.over_sampling.base import BaseOverSampler


def _generate_classes_stats(y, majority_label, imbalance_ratio_threshold, k_neighbors):
    """Generate stats for the various minority classes."""
    counter = Counter(y)
    stats = {label:((counter[majority_label]/ n_samples), n_samples) for label, n_samples in counter.items()
             if label != majority_label}
    include_group = any([ir < imbalance_ratio_threshold and n_samples > k_neighbors
                         if k_neighbors is not None else ir < imbalance_ratio_threshold
                         for label, (ir, n_samples) in stats.items()])
    modified_imbalance_ratios = {label: ((counter[majority_label] + 1) / (n_samples + 1))
                                 for label, n_samples in counter.items()
                                 if label != majority_label}
    return include_group, modified_imbalance_ratios


class ExtendedBaseOverSampler(BaseOverSampler):
    """An extension of the base class for over-sampling algorithms to
    handle categorical features.

    Warning: This class should not be used directly. Use the derive classes
    instead.
    """

    def __init__(self,
                 ratio='auto',
                 random_state=None,
                 sampling_type=None,
                 integer_cols=None,
                 categorical_cols=None,
                 imbalance_ratio_threshold=1.0):
        super(ExtendedBaseOverSampler, self).__init__(ratio, random_state, sampling_type)
        self.integer_cols = integer_cols
        self.categorical_cols = categorical_cols
        self.imbalance_ratio_threshold = imbalance_ratio_threshold

    @abstractmethod
    def _partial_sample(self, X, y):
        """Resample the numerical features of the dataset.

        Parameters
        ----------
        X : {array-like, sparse matrix}, shape (n_samples, n_features)
            Matrix containing the numerical data which have to be sampled.

        y : array-like, shape (n_samples,)
            Corresponding label for each sample in X.

        Returns
        -------
        X_resampled : {ndarray, sparse matrix}, shape (n_samples_new, n_features)
            The array containing the numerical resampled data.

        y_resampled : ndarray, shape (n_samples_new,)
            The corresponding label of `X_resampled`
        """
        pass

    def _sample(self, X, y):
        """Resample the dataset.

        Parameters
        ----------
        X : {array-like, sparse matrix}, shape (n_samples, n_features)
            Matrix containing the data which have to be sampled.

        y : array-like, shape (n_samples,)
            Corresponding label for each sample in X.

        Returns
        -------
        X_resampled : {ndarray, sparse matrix}, shape (n_samples_new, n_features)
            The array containing the resampled data.

        y_resampled : ndarray, shape (n_samples_new,)
            The corresponding label of `X_resampled`
        """

        self.random_state_ = check_random_state(self.random_state)

        if self.categorical_cols is None:
            return self._partial_sample(X, y)

        max_col_index = X.shape[1]

        try:
            if len(self.integer_cols) == 0 or not set(range(max_col_index)).issuperset(self.integer_cols):
                error_msg = 'Selected integer columns should be in the {} range. Got {} instead.'
                raise ValueError(error_msg.format([0, max_col_index], self.integer_cols))
        except:
            raise ValueError('Parameter `integer_cols` should be a list or tuple in the %s range.' % [0, max_col_index])

        try:
            if len(self.categorical_cols) == 0 or not set(range(max_col_index)).issuperset(self.categorical_cols):
                error_msg = 'Selected categorical columns should be in the {} range. Got {} instead.'
                raise ValueError(error_msg.format([0, max_col_index], self.categorical_cols))
        except:
            raise ValueError('Parameter `categorical_cols` should be a list or tuple in the %s range.' % [0, max_col_index])

        if not set(self.integer_cols).isdisjoint(self.categorical_cols):
            raise ValueError('Parameters `integer_cols` and `categorical_cols` should not have common elements.')

        if self.imbalance_ratio_threshold <= 0.0:
            raise ValueError('Parameter `categorical_threshold` should be a positive number.')

        df = pd.DataFrame(np.column_stack((X, y)))

        # Select groups to oversample
        majority_label = [label for label, n_samples in self.ratio_.items() if n_samples == 0][0]
        minority_labels = [label for label in self.ratio_.keys() if label != majority_label]
        classes_stats = df.groupby(self.categorical_cols, as_index=False).agg(
            {
                df.columns[-1]: lambda y: _generate_classes_stats(
                    y,
                    majority_label,
                    self.imbalance_ratio_threshold,
                    self.k_neighbors if hasattr(self, 'k_neighbors') else None
                )
            }
        )
        boolean_mask = classes_stats.iloc[:, -1].apply(lambda stat: stat[0])
        included_groups = classes_stats[boolean_mask].iloc[:, :-1].reset_index(drop=True)
        self.n_overasmpled_groups_ = len(included_groups)

        # Calculate oversampling weights
        imbalance_ratios = classes_stats[boolean_mask].iloc[:, -1].apply(lambda stat: stat[1]).reset_index(drop=True)
        weights = pd.DataFrame()
        for label in minority_labels:
            label_weights = imbalance_ratios.apply(lambda ratio: ratio.get(label, np.nan))
            label_weights = label_weights / label_weights.sum()
            label_weights.rename(label, inplace=True)
            weights = pd.concat([weights, label_weights], axis=1)

        initial_ratio = self.ratio_.copy()

        X_resampled = pd.DataFrame(columns=df.columns[:-1])
        y_resampled = pd.DataFrame(columns=[df.columns[-1]])

        # Oversample data in each group
        for group_values, (_, weight) in zip(included_groups.values.tolist(), weights.iterrows()):

            # Define ratio in group
            self.ratio_ = {label: (int(n_samples * weight[label]) if label != majority_label else n_samples)
                           for label, n_samples in initial_ratio.items()}

            # Select data in group
            df_group = pd.merge(df, pd.DataFrame([group_values], columns=self.categorical_cols)).drop(columns=self.categorical_cols)
            X_group, y_group = df_group.iloc[:, :-1], df_group.iloc[:, -1]

            # Oversample data
            X_group_resampled, y_group_resampled = self._partial_sample(X_group.values, y_group.values)
            X_group_categorical = np.array(group_values * len(X_group_resampled)).reshape(len(X_group_resampled), -1)
            X_group_resampled = np.column_stack((X_group_resampled, X_group_categorical))
            X_group_resampled = pd.DataFrame(X_group_resampled, columns=list(X_group.columns) + self.categorical_cols)
            y_group_resampled = pd.DataFrame(y_group_resampled, columns=y_resampled.columns)

            # Append resampled data
            X_resampled = X_resampled.append(X_group_resampled.loc[:, X_resampled.columns])
            y_resampled = y_resampled.append(y_group_resampled)

        # Restore ratio
        self.ratio_ = initial_ratio.copy()

        # Append excluded data
        excluded_groups = classes_stats[~boolean_mask].iloc[:, :-1].reset_index(drop=True)
        df_excluded = pd.merge(df, excluded_groups)
        X_resampled = X_resampled.append(df_excluded.iloc[:, :-1]).values
        y_resampled = y_resampled.append(df_excluded.iloc[:, -1:]).values.reshape(-1)

        # Integer columns
        X_resampled[:, self.integer_cols] = np.round(X_resampled[:, self.integer_cols]).astype(int)

        return X_resampled, y_resampled
