import random
import torch
from torch.utils.data import Dataset, DataLoader
import pandas as pd
from urllib.parse import urlparse
from superdebug import debug

class RedditDataset(Dataset):
    def __init__(self, config, data:pd.DataFrame, categorical_features, string_features, target, weight = None, sample_voted_users = None, add_target_user_ratio = 0, interactive = False):
        super(RedditDataset, self).__init__()
        self.data = data
        self.df_indices = self.data.index.to_numpy(int)
        self.categorical_features = categorical_features
        self.string_features = string_features
        self.sample_voted_users = sample_voted_users
        self.use_voted_users_feature = config["use_voted_users_feature"]
        self.add_target_user_ratio = add_target_user_ratio
        self.interactive = interactive

        self.featured_data = {}
        for feat in self.categorical_features:
            self.featured_data[feat] = data[feat].to_numpy(int)
        for feat in self.string_features:
            if feat in data:
                self.featured_data[feat] = data[feat].to_list()
                if feat == "SUBMISSION_URL":
                    self.featured_data[feat] = [urlparse(_).netloc for _ in self.featured_data[feat]]
        if self.use_voted_users_feature:
            for feat in ["UPVOTED_USERS", "DOWNVOTED_USERS"]:
                self.featured_data[feat] = data[feat].to_list()
        for feat in self.featured_data:
            assert len(self.featured_data[feat]) == len(self.data)
        self.weight = weight
        assert self.weight is None or len(self.weight) == len(self.data)
        self.target_data = data[target[0]].to_numpy()
        assert all(self.target_data <= 1)
        assert len(self.target_data) == len(self.data)
        
    def __len__(self):
        return len(self.data)

    def modify_updown_voted_users(self, updown_voted_users, target_user, label, vote = "upvote"):
        if type(updown_voted_users) != set:
            updown_voted_users = set(updown_voted_users)
        if 0 in updown_voted_users:
            updown_voted_users.remove(0)
        modified_updown_voted_users = None
        
        # sample voted users
        if self.sample_voted_users:
            if not self.interactive:
                weight = 1/3
                sample_weights = [weight]
                for weight_i in range(len(updown_voted_users)):
                    weight = weight * 2/3
                    sample_weights.append(weight)
                random.seed(42)
                sample_num = random.choices(list(range(len(updown_voted_users) + 1)), sample_weights)[0]
                random.seed(42)
                modified_updown_voted_users = random.sample(list(updown_voted_users), sample_num)
            else:
                print(f"Original {vote}d users:", list(updown_voted_users))
                selected_users = input(f"Please select {vote}d users (they will later further converted to USERNAME_i, input '.' to stop): ")
                if selected_users == ".":
                    return None
                modified_updown_voted_users = [int(user) for user in selected_users.split() if int(user) != 0]
                print(f"New {vote}d users:", modified_updown_voted_users)
        else:
            modified_updown_voted_users = list(updown_voted_users)

        # add target user to peers
        random.seed(42)
        if self.add_target_user_ratio != 0 and random.random() < self.add_target_user_ratio:
            if (label == 0 and vote == "downvote") or (label == 1 and vote == "upvote"):
                # modified_updown_voted_users.append(target_user)
                modified_updown_voted_users = [target_user]

        if modified_updown_voted_users is None:
            modified_updown_voted_users = list(modified_updown_voted_users)
        return modified_updown_voted_users
        
        
    def __getitem__(self,idx):
        label = self.target_data[idx]
        strings = []
        for feat in self.categorical_features:
            strings.append(f"[{feat}]")
            strings.append(f"{feat}_{self.featured_data[feat][idx]}")
        for feat in self.string_features:
            if feat in self.featured_data:
                strings.append(f"[{feat}]")
                strings.append(str(self.featured_data[feat][idx]))
        if self.use_voted_users_feature:
            target_user = self.featured_data["USERNAME"][idx]
            for vote in ["upvote", "downvote"]:
                updown_voted_users = self.featured_data[f"{vote.upper()}D_USERS"][idx]
                updown_voted_users = self.modify_updown_voted_users(updown_voted_users, target_user, label, vote)
                if updown_voted_users is None:
                    return None
                strings.append(f"[{vote.upper()}D_USERS]")
                for user in updown_voted_users:
                    strings.append(f"USERNAME_{user}")
        input_string = " ".join(strings)
        if self.weight is None:
            weight = 1.0
        else:
            weight = self.weight[idx]
        df_index = self.df_indices[idx]
        return input_string, label, weight, df_index


class CollateFN:
    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
    def __call__(self, data):
        """
        data: is a list of tuples with (input_string, label, weight)
        """
        input_strings, labels, weights, df_indices = zip(*data)
        tokenized_input_strings = self.tokenizer(list(input_strings), padding=True, truncation=True, max_length=512, return_tensors="pt") # contains: input_ids, token_type_ids, attention_mask
        # raise
        input_ids = tokenized_input_strings["input_ids"]
        token_type_ids = tokenized_input_strings.get("token_type_ids", None)
        attention_mask = tokenized_input_strings["attention_mask"]
        labels = torch.tensor(labels)
        weights = torch.tensor(weights)
        df_indices = torch.tensor(df_indices)
        return input_ids, token_type_ids, attention_mask, labels, weights, df_indices
        # features.float(), labels.long(), lengths.long()

def get_data_loader(config, data:pd.DataFrame, tokenizer, categorical_features, string_features, target, weight = None, interactive = False, sample_voted_users = True, add_target_user_ratio = 0, shuffle=True, batch_size=256):
    dataset = RedditDataset(config, data, categorical_features, string_features, target, weight=weight, sample_voted_users=sample_voted_users, add_target_user_ratio=add_target_user_ratio, interactive=interactive)
    collate_fn = CollateFN(tokenizer)
    data_loader = DataLoader(dataset=dataset, shuffle=shuffle, batch_size=batch_size, collate_fn=collate_fn)
    return dataset, data_loader