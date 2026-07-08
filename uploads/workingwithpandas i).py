import pandas as pd
# 1. Creating a DataFrame from a dictionary
data = {
    'Name': ['Alice', 'Bob', 'Charlie', 'David', 'Eva'],
    'Age': [24, 27, 22, 32, 29],
    'Department': ['HR', 'Finance', 'IT', 'HR', 'IT'],
    'Salary': [50000, 60000, 45000, 52000, 58000]
}
df = pd.DataFrame(data)
print("Original DataFrame:\n", df)

# 2. Viewing basic information
print("\nDataFrame Info:")
print(df.info())
print("\nSummary Statistics:\n", df.describe())
print("\nData Types:\n", df.dtypes)

# 3. Accessing data
print("\nAccessing 'Name' column:\n", df['Name'])
print("\nAccessing first two rows:\n", df.head(2))
print("\nAccessing specific element (row 0, column 'Salary'):", df.loc[0, 'Salary'])

# 4. Filtering data
high_salary = df[df['Salary'] > 55000]
print("\nEmployees with Salary > 55000:\n", high_salary)

# 5. Adding a new column
df['Bonus'] = df['Salary'] * 0.1
print("\nDataFrame after adding Bonus column:\n", df)

# 6. Modifying data
df.at[1, 'Department'] = 'Marketing'
print("\nDataFrame after modifying Bob's department:\n", df)

# 7. Sorting the DataFrame
sorted_df = df.sort_values(by='Salary', ascending=False)
print("\nDataFrame sorted by Salary (descending):\n", sorted_df)




